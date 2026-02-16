from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from aetherflow.core.runner import run_flow
from aetherflow.core.runtime.settings import load_settings


def _write_flow(tmp_path: Path, name: str, yaml_text: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(yaml_text).strip() + "\n", encoding="utf-8")
    return p


def test_run_summary_emitted_in_json_logs(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    flow = _write_flow(
        tmp_path,
        "flow_obs.yaml",
        """
        version: 1
        flow:
          id: obs
          workspace:
            root: '{work}'
            cleanup_policy: never
          state:
            backend: sqlite
            path: '{state}'
        jobs:
          - id: j
            steps:
              - id: check
                type: check_items
                inputs:
                  items: [1, 2, 3]
        """.format(
            work=str(tmp_path / "work"),
            state=str(tmp_path / "state.sqlite"),
        ),
    )

    settings = load_settings({"log_level": "INFO", "log_format": "json"})
    caplog.set_level("INFO")
    run_flow(str(flow), settings=settings)

    # Find the final run_summary event
    summaries = []
    for rec in caplog.records:
        msg = rec.getMessage()
        try:
            data = json.loads(msg)
        except Exception:
            continue
        if data.get("event") == "run_summary":
            summaries.append(data)

    assert summaries, "Expected a run_summary event in JSON logs"
    s = summaries[-1]
    assert s["flow_id"] == "obs"
    assert "duration_ms" in s
    assert s["status_counts"].get("SUCCESS") == 1
    assert len(s["jobs"]) == 1
    assert s["jobs"][0]["job_id"] == "j"