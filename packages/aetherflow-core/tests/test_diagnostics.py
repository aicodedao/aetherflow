from __future__ import annotations

import json
from pathlib import Path

import yaml

from aetherflow.core.diagnostics import doctor_check_env, explain_profiles_env


def _write(p: Path, txt: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


def test_doctor_missing_env_keys(tmp_path: Path, monkeypatch):
    profiles = tmp_path / "profiles.yaml"
    _write(
        profiles,
        yaml.safe_dump(
            {
                "oracle_main": {
                    "config": {"user": "{{env.ORA_USER}}", "password": "{{env.ORA_PASS}}", "dsn": "{{env.ORA_DSN}}"},
                    "decode": {"config": {"password": True}},
                }
            },
            sort_keys=False,
        ),
    )

    flow = tmp_path / "flow.yaml"
    _write(
        flow,
        """
version: 1
flow:
  id: demo
  workspace: {root: /tmp/work}
  state: {path: ":memory:"}
resources:
  ora:
    kind: oracle
    driver: cx_oracle
    profile: oracle_main
jobs: []
""".lstrip(),
    )

    monkeypatch.setenv("AETHERFLOW_PROFILES_FILE", str(profiles))
    monkeypatch.delenv("ORA_PASS", raising=False)
    monkeypatch.setenv("ORA_USER", "u")
    monkeypatch.setenv("ORA_DSN", "dsn")

    rep = doctor_check_env(str(flow))
    assert rep["ok"] is False
    # doctor report uses FlowValidationIssue.as_dict(): {code, loc, msg}
    assert any("ORA_PASS" in it.get("msg", "") for it in rep["missing_env"])


def test_doctor_env_files_dotenv(tmp_path: Path, monkeypatch):
    profiles = tmp_path / "profiles.yaml"
    _write(
        profiles,
        yaml.safe_dump(
            {
                "oracle_main": {
                    "config": {"user": "{{env.ORA_USER}}", "password": "{{env.ORA_PASS}}", "dsn": "{{env.ORA_DSN}}"},
                    "decode": {"config": {"password": True}},
                }
            },
            sort_keys=False,
        ),
    )

    envfile = tmp_path / "common.env"
    _write(envfile, "ORA_PASS=c29tZXBhc3M=\n")

    flow = tmp_path / "flow.yaml"
    _write(
        flow,
        """
version: 1
flow:
  id: demo
  workspace: {root: /tmp/work}
  state: {path: ":memory:"}
resources:
  ora:
    kind: oracle
    driver: cx_oracle
    profile: oracle_main
jobs: []
""".lstrip(),
    )

    monkeypatch.setenv("AETHERFLOW_PROFILES_FILE", str(profiles))
    monkeypatch.setenv("ORA_USER", "u")
    monkeypatch.setenv("ORA_DSN", "dsn")
    monkeypatch.setenv(
        "AETHERFLOW_ENV_FILES_JSON",
        json.dumps([{"type": "dotenv", "path": str(envfile)}]),
    )

    rep = doctor_check_env(str(flow))
    assert rep["ok"] is True


def test_explain_shows_decode_and_redaction(tmp_path: Path, monkeypatch):
    profiles = tmp_path / "profiles.yaml"
    _write(
        profiles,
        yaml.safe_dump(
            {
                "oracle_main": {
                    "config": {"user": "{{env.ORA_USER}}", "password": "{{env.ORA_PASS}}"},
                    "decode": {"config": {"password": True}},
                }
            },
            sort_keys=False,
        ),
    )
    flow = tmp_path / "flow.yaml"
    _write(
        flow,
        """
version: 1
flow:
  id: demo
  workspace: {root: /tmp/work}
  state: {path: ":memory:"}
resources:
  ora:
    kind: oracle
    driver: cx_oracle
    profile: oracle_main
jobs: []
""".lstrip(),
    )

    monkeypatch.setenv("AETHERFLOW_PROFILES_FILE", str(profiles))
    monkeypatch.setenv("ORA_USER", "u")
    monkeypatch.setenv("ORA_PASS", "c29tZXBhc3M=")

    rep = explain_profiles_env(str(flow))
    ora = rep["resources"]["ora"]
    # New contract: explain focuses on profile selection + decode config (no env mapping list).
    assert ora["profile"] == "oracle_main"
    assert ora["decode"] == {"config": {"password": True}}


from aetherflow.core.diagnostics import build_env_snapshot

def test_enterprise_mode_ignores_bundle_plugins_dir(tmp_path: Path, monkeypatch):
    # Prepare a "remote" bundle directory with plugins/ and flows/
    remote = tmp_path / "remote_bundle"
    (remote / "plugins").mkdir(parents=True)
    (remote / "plugins" / "p1.py").write_text("def register():\n    return\n", encoding="utf-8")
    (remote / "flows").mkdir(parents=True)
    (remote / "flows" / "main.yaml").write_text("flow: {}", encoding="utf-8")
    (remote / "profiles.yaml").write_text("{}", encoding="utf-8")

    manifest = tmp_path / "bundle.yaml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "mode": "enterprise",
                "bundle": {
                    "id": "t",
                    "source": {"type": "filesystem", "base_path": str(remote)},
                    "layout": {"plugins_dir": "plugins", "profiles_file": "profiles.yaml"},
                    "entry_flow": "flows/main.yaml",
                },
            }
        ),
        encoding="utf-8",
    )

    # Even if the ambient OS environment has plugin paths, enterprise mode must hard-deny them.
    monkeypatch.setenv("AETHERFLOW_PLUGIN_PATHS", "/tmp/evil")

    env_snapshot, settings, bundle_root, sources, allowed_archive_drivers = build_env_snapshot(bundle_manifest=str(manifest))
    assert bundle_root is not None
    # In enterprise mode, bundle.layout.plugins_dir must not be mapped into AETHERFLOW_PLUGIN_PATHS
    assert "AETHERFLOW_PLUGIN_PATHS" not in env_snapshot
