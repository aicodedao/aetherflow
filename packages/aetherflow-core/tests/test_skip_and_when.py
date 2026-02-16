from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from aetherflow.core.steps.base import Step, StepResult, STEP_SKIPPED
from aetherflow.core.registry.steps import register_step
from aetherflow.core.runner import run_flow
from aetherflow.core.runtime.settings import load_settings


@register_step("_test_skip")
class _TestSkipStep(Step):
    def run(self):
        return StepResult(status=STEP_SKIPPED, output={"has_data": False, "count": 0}, reason="no data")


@register_step("_test_boom")
class _TestBoomStep(Step):
    def run(self):
        raise RuntimeError("boom step should not run")


def _write_flow(tmp_path: Path, name: str, yaml_text: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(yaml_text).strip() + "\n", encoding="utf-8")
    return p


def test_step_on_no_data_skip_job(tmp_path: Path):
    flow = _write_flow(
        tmp_path,
        "flow.yaml",
        """
        version: 1
        flow:
          id: t
          workspace:
            root: '{work}'
            cleanup_policy: never
          state:
            backend: sqlite
            path: '{state}'
        jobs:
          - id: j
            steps:
              - id: probe
                type: _test_skip
                on_no_data: skip_job
              - id: should_not_run
                type: _test_boom
        """.format(
            work=str(tmp_path / "work"),
            state=str(tmp_path / "state.sqlite"),
        ),
    )

    settings = load_settings({"log_level": "CRITICAL"})
    # Should not raise; boom step must be skipped.
    run_flow(str(flow), settings=settings)


def test_job_when_gates_downstream_job(tmp_path: Path):
    flow = _write_flow(
        tmp_path,
        "flow2.yaml",
        """
        version: 1
        flow:
          id: t2
          workspace:
            root: '{work}'
            cleanup_policy: never
          state:
            backend: sqlite
            path: '{state}'
        jobs:
          - id: probe
            steps:
              - id: check
                type: check_items
                inputs:
                  items: []
                outputs:
                  has_data: "{{{{ result.has_data }}}}"
          - id: process
            depends_on: [probe]
            when: jobs.probe.outputs.has_data == true
            steps:
              - id: should_not_run
                type: _test_boom
        """.format(
            work=str(tmp_path / "work2"),
            state=str(tmp_path / "state2.sqlite"),
        ),
    )

    settings = load_settings({"log_level": "CRITICAL"})
    run_flow(str(flow), settings=settings)
