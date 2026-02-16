import os
import sys
from pathlib import Path

import pytest

from aetherflow.core.context import RunContext
from aetherflow.core.state import StateStore
from aetherflow.core.builtins.steps import ExternalProcess
from aetherflow.core.validation import validate_flow_dict


def _ctx(settings, tmp: Path):
    state = StateStore(str(tmp / "state.sqlite"))
    return RunContext(
        settings=settings,
        flow_id="f",
        run_id="r123",
        work_root=tmp,
        layout={"artifacts": "artifacts", "scratch": "scratch", "manifests": "manifests"},
        state=state,
        resources={},
        connectors={},
    )


def test_external_process_atomic_dir_success(temp_dir, settings):
    ctx = _ctx(settings, temp_dir)
    job_id = "job"

    # Write into temp output dir; step will move it to final.
    temp_out = "out/.tmp_{{env.run_id}}"
    final_out = "out/final"
    marker = "out/final/_SUCCESS"

    cmd = [
        sys.executable,
        "-c",
        (
            "import os, pathlib; "
            "out=os.environ.get('AETHERFLOW_OUTPUT_DIR'); "
            "pathlib.Path(out).mkdir(parents=True, exist_ok=True); "
            "(pathlib.Path(out)/'data.txt').write_text('ok'); "
            "(pathlib.Path(out)/'_SUCCESS').write_text('1')"
        ),
    ]

    step = ExternalProcess(
        "s",
        {
            "command": cmd,
            "idempotency": {"strategy": "atomic_dir", "temp_output_dir": temp_out, "final_output_dir": final_out},
            "success": {"marker_file": marker},
        },
        ctx,
        job_id,
    )

    out = step.run()
    assert out["exit_code"] == 0
    final_dir = (ctx.artifacts_dir(job_id) / "out/final").resolve()
    assert (final_dir / "data.txt").read_text() == "ok"
    assert (final_dir / "_SUCCESS").exists()


def test_external_process_marker_skips(temp_dir, settings):
    ctx = _ctx(settings, temp_dir)
    job_id = "job"
    marker = ctx.artifacts_dir(job_id) / "done/_SUCCESS"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("1")

    # Command would create a file if executed; we assert it doesn't.
    ran = ctx.artifacts_dir(job_id) / "done/ran.txt"
    cmd = [sys.executable, "-c", f"from pathlib import Path; Path(r'{ran}').write_text('ran')"]

    step = ExternalProcess(
        "s",
        {
            "command": cmd,
            "idempotency": {"strategy": "marker", "marker_path": "done/_SUCCESS"},
            "success": {"marker_file": "done/_SUCCESS"},
        },
        ctx,
        job_id,
    )

    res = step.run()
    assert res.status == "SKIPPED"
    assert not ran.exists()


def test_external_process_timeout_retry(temp_dir, settings):
    ctx = _ctx(settings, temp_dir)
    job_id = "job"
    cmd = [sys.executable, "-c", "import time; time.sleep(0.2)"]

    step = ExternalProcess(
        "s",
        {
            "command": cmd,
            "timeout_seconds": 0.05,
            "retry": {"max_attempts": 2, "retry_on_timeout": True},
        },
        ctx,
        job_id,
    )

    with pytest.raises(TimeoutError):
        step.run()


def test_validation_external_process_missing_command(settings):
    raw = {
        "version": 1,
        "flow": {"id": "x"},
        "jobs": [
            {
                "id": "j",
                "steps": [
                    {"id": "s", "type": "external.process", "inputs": {}},
                ],
            }
        ],
    }
    rep = validate_flow_dict(raw, settings=settings)
    assert rep["ok"] is False
    codes = {e["code"] for e in rep["errors"]}
    assert "semantic:external_process_missing_command" in codes
