from __future__ import annotations

import os
import types
from pathlib import Path

import pytest
import yaml

from aetherflow.core.bundles import validate_bundle_manifest_v1
from aetherflow.core.exception import SpecError
from aetherflow.core.resolution import (
    ResolverMissingKeyError,
    ResolverSyntaxError,
    render_string,
    resolve_resource,
)
from aetherflow.core.validation import validate_flow_yaml


UNSUPPORTED_MSG = "Unsupported templating syntax. Use {{VAR}} or {{VAR:DEFAULT}}"


def _dummy_set_envs():
    def expand_env(env: dict[str, str]) -> dict[str, str]:
        return dict(env)

    def decode(v: str) -> str:
        # obvious marker for tests
        return f"DEC({v})"

    return types.SimpleNamespace(expand_env=expand_env, decode=decode)


def test_unknown_key_raises_missing_key_error():
    with pytest.raises(ResolverMissingKeyError):
        render_string("{{env.DOES_NOT_EXIST}}", mapping={"env": {}})


@pytest.mark.parametrize(
    "s",
    [
        "$" + "{X}",
        "{}",
        "{% if x %}",
        "{# c #}",
    ],
)
def test_forbidden_syntax_rejected(s: str):
    with pytest.raises(ResolverSyntaxError) as ei:
        render_string(s, mapping={"env": {"X": "1"}})
    assert str(ei.value).startswith(UNSUPPORTED_MSG)


def test_decode_concatenation_error_raises_syntax():
    # Decode requested and raw value concatenates a template -> hard fail.
    r = {
        "kind": "http",
        "driver": "requests",
        "config": {"headers": {"Authorization": "Bearer {{env.TOKEN}}"}},
        "options": {},
        "decode": {"config": {"headers": {"Authorization": True}}},
    }
    with pytest.raises(ResolverSyntaxError) as ei:
        resolve_resource(r, env={"TOKEN": "abc"}, set_envs_module=_dummy_set_envs())
    assert str(ei.value).startswith(UNSUPPORTED_MSG)


def test_flow_resource_decode_works(tmp_path: Path, monkeypatch):
    # Use AETHERFLOW_SECRETS_MODULE to provide expand_env + decode.
    mod = tmp_path / "set_envs_mod.py"
    mod.write_text(
        """
def expand_env(env):
    return dict(env)

def decode(v: str) -> str:
    return "DEC(" + v + ")"
""".lstrip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("AETHERFLOW_SECRETS_MODULE", "set_envs_mod")
    monkeypatch.setenv("TOKEN", "abc")

    flow = tmp_path / "flow.yaml"
    flow.write_text(
        """
version: 1
flow:
  id: demo
resources:
  r1:
    kind: http
    driver: requests
    config:
      token: "{{env.TOKEN}}"
    decode:
      config:
        token: true
jobs:
  - id: j
    steps:
      - id: s
        type: check_items
        inputs:
          items: []
""".lstrip(),
        encoding="utf-8",
    )

    # Run through validation (ensures parsing + contract enforcement succeeds)
    rep = validate_flow_yaml(str(flow))
    assert rep["ok"] is True

    # And directly validate resolver behavior on resource payload
    resolved = resolve_resource(
        {
            "kind": "http",
            "driver": "requests",
            "config": {"token": "{{env.TOKEN}}"},
            "options": {},
            "decode": {"config": {"token": True}},
        },
        env=dict(os.environ),
        set_envs_module=_dummy_set_envs(),
    )
    assert resolved["config"]["token"] == "DEC(abc)"


def test_manifest_resource_decode_works(tmp_path: Path):
    r = {
        "kind": "http",
        "driver": "requests",
        "config": {"token": "{{env.TOKEN}}"},
        "options": {},
        "decode": {"config": {"token": True}},
    }
    resolved = resolve_resource(r, env={"TOKEN": "abc"}, set_envs_module=_dummy_set_envs())
    assert resolved["config"]["token"] == "DEC(abc)"


def test_manifest_rejects_profile_with_exact_message(tmp_path: Path):
    mf = {
        "version": 1,
        "bundle": {
            "id": "x",
            "source": {"type": "filesystem", "base_path": "/tmp"},
            "layout": {"profiles_file": "profiles.yaml"},
            "entry_flow": "flows/demo.yaml",
        },
        "resources": {
            "r1": {"kind": "db", "driver": "sqlite3", "profile": "p1", "config": {}},
        },
    }
    with pytest.raises(ValueError) as ei:
        validate_bundle_manifest_v1(mf, bundle_manifest=str(tmp_path / "bundle.yaml"))
    assert str(ei.value) == "manifest is bootstrap; profiles not available before sync"


@pytest.mark.parametrize("field", ["config" + "_env", "options" + "_env", "decode" + "_env"])
def test_legacy_env_fields_rejected_in_flow_yaml(tmp_path: Path, field: str):
    flow = tmp_path / f"bad_{field}.yaml"
    flow.write_text(
        f"""
version: 1
flow:
  id: demo
resources:
  r1:
    kind: db
    driver: sqlite3
    {field}: {{path: "ENV"}}
jobs:
  - id: j
    steps:
      - id: s
        type: check_items
        inputs:
          items: []
""".lstrip(),
        encoding="utf-8",
    )
    rep = validate_flow_yaml(str(flow))
    assert rep["ok"] is False
    # Pydantic schema error for extra field
    assert any(field in (e.get("loc", "") + " " + e.get("msg", "")) for e in rep["errors"])
