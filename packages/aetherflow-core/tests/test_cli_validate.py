from __future__ import annotations

import json

from aetherflow.core.cli import main


def test_cli_validate_ok(tmp_path, capsys):
    flow = tmp_path / "flow.yaml"
    flow.write_text(
        """
version: 1
flow:
  id: demo
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          items: []
""",
        encoding="utf-8",
    )

    rc = main(["validate", "--flow-yaml", str(flow)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK:" in out


def test_cli_validate_json_and_exitcode(tmp_path, capsys):
    flow = tmp_path / "bad.yaml"
    # missing flow.id
    flow.write_text(
        """
version: 1
flow: {}
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          items: []
""",
        encoding="utf-8",
    )

    rc = main(["validate", "--flow-yaml", str(flow), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 2
    assert payload["ok"] is False
    assert payload["errors"]


def test_cli_validate_warns_on_missing_profile_env(tmp_path, capsys, monkeypatch):
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        """
oracle_main:
  config:
    user: "{{env.ORA_USER}}"
    password: "{{env.ORA_PASS}}"
  decode:
    config:
      password: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AETHERFLOW_PROFILES_FILE", str(profiles))
    # Ensure required env keys are missing
    monkeypatch.delenv("ORA_USER", raising=False)
    monkeypatch.delenv("ORA_PASS", raising=False)

    flow = tmp_path / "flow.yaml"
    flow.write_text(
        """
version: 1
flow:
  id: demo
resources:
  ora:
    kind: db
    driver: oracle
    profile: oracle_main
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          items: []
""",
        encoding="utf-8",
    )

    rc = main(["validate", "--flow-yaml", str(flow)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "OK:" in out
    # Under the new resolver contract, missing env referenced by profiles is reported.
    assert "semantic:missing_env" in out


def test_cli_validate_strict_env_fails(tmp_path, capsys, monkeypatch):
    profiles = tmp_path / "profiles.yaml"
    profiles.write_text(
        """
oracle_main:
  config:
    password: "{{env.ORA_PASS}}"
  decode:
    config:
      password: true
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("AETHERFLOW_PROFILES_FILE", str(profiles))
    monkeypatch.setenv("AETHERFLOW_VALIDATE_ENV_STRICT", "true")
    monkeypatch.delenv("ORA_PASS", raising=False)

    flow = tmp_path / "flow.yaml"
    flow.write_text(
        """
version: 1
flow:
  id: demo
resources:
  ora:
    kind: db
    driver: oracle
    profile: oracle_main
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          items: []
""",
        encoding="utf-8",
    )

    rc = main(["validate", "--flow-yaml", str(flow), "--json"])
    out = capsys.readouterr().out
    json_text = next((line for line in out.splitlines()[::-1] if line.strip().startswith("{")), "")
    #print("TEST ", json_text, rc)
    payload = json.loads(json_text)
    # Strict env missing must fail validation with exit code 2.
    assert rc == 2
    assert payload["ok"] is False
    assert any(e["code"] == "semantic:missing_env" for e in payload["errors"])