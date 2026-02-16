from __future__ import annotations

import pytest

from aetherflow.core.cli import main
from aetherflow.core.exception import SpecError
from aetherflow.core.validation import validate_flow_yaml


STRICT_ERR = "Unsupported templating syntax. Use {{VAR}} or {{VAR:DEFAULT}}"
DECODE_ERR = "Decode target must be a standalone template token like '{{TOKEN}}' (no prefix/suffix)."


def test_cli_run_cannot_bypass_validation(tmp_path):
    flow = tmp_path / "flow.yaml"
    bad = "$" + "{BAD}"
    flow.write_text(
        f'''
version: 1
flow:
  id: demo
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          # legacy syntax must fail before running steps
          items: "{bad}"
''',
        encoding="utf-8",
    )

    with pytest.raises(SpecError) as e:
        main(["run", "--flow-yaml", str(flow)])

    assert STRICT_ERR in str(e.value)


def test_enterprise_mode_does_not_relax_templating(tmp_path, monkeypatch):
    monkeypatch.setenv("AETHERFLOW_MODE_ENTERPRISE", "true")

    flow = tmp_path / "flow.yaml"
    flow.write_text(
        '''
version: 1
flow:
  id: demo
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          items: ["{{ x | lower }}"]
''',
        encoding="utf-8",
    )

    report = validate_flow_yaml(str(flow))
    assert report["ok"] is False
    assert any(STRICT_ERR in (e.get("msg") or "") for e in report.get("errors", []))


def test_flow_resource_decode_concat_is_rejected(tmp_path):
    flow = tmp_path / "flow.yaml"
    flow.write_text(
        '''
version: 1
flow:
  id: demo
resources:
  api:
    kind: http
    driver: http
    config:
      headers:
        Authorization: "Bearer {{env.API_TOKEN}}"
    decode:
      config:
        headers:
          Authorization: true
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          items: []
''',
        encoding="utf-8",
    )

    report = validate_flow_yaml(str(flow))
    assert report["ok"] is False
    assert any(DECODE_ERR in (e.get("msg") or "") for e in report.get("errors", []))
