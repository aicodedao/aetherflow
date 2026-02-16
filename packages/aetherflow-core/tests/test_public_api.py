def test_api_exports_exist():
    from aetherflow.core.api import (
        Step,
        StepResult,
        STEP_SUCCESS,
        STEP_SKIPPED,
        RunContext,
        Settings,
        FlowSpec,
        register_step,
        list_steps,
        register_connector,
        list_connectors,
    )

    assert Step is not None
    assert StepResult is not None
    assert STEP_SUCCESS in {"SUCCESS", "SKIPPED"} or STEP_SUCCESS == "SUCCESS"
    assert STEP_SKIPPED == "SKIPPED"
    assert RunContext is not None
    assert Settings is not None
    assert FlowSpec is not None
    assert callable(register_step)
    assert callable(list_steps)
    assert callable(register_connector)
    assert callable(list_connectors)

def test_no_ambiguous_top_level_modules_exist():
    """Strict import rule: do not ship ambiguous top-level modules like aetherflow.core.api."""
    import importlib.util

    assert importlib.util.find_spec("aetherflow.api") is None
    assert importlib.util.find_spec("aetherflow.builtins") is None
