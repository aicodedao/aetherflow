from __future__ import annotations

import aetherflow.core.api as api


def test_public_api___all___is_frozen():
    """Contract test: keep `aetherflow.core.api.__all__` stable.

    If you *intentionally* change the public API, update this test, the SemVer doc,
    and `CHANGELOG.md`.
    """
    expected = [
        # steps
        "Step",
        "StepResult",
        "STEP_SUCCESS",
        "STEP_SKIPPED",
        # context
        "RunContext",
        "new_run_id",
        # settings
        "Settings",
        # spec
        "FlowSpec",
        "FlowMetaSpec",
        "JobSpec",
        "StepSpec",
        "ResourceSpec",
        "WorkspaceSpec",
        "StateSpec",
        "LocksSpec",
        "CleanupPolicy",
        "LockScope",
        "RemoteFileMeta",
        # connectors
        "ConnectorBase",
        "ConnectorInit",
        "ConnectorError",
        # registries
        "register_step",
        "get_step",
        "list_steps",
        "register_connector",
        "get_connector",
        "list_connectors",
        "require",
        "require_attr",
    ]

    assert list(api.__all__) == expected


def test_public_api_exports_exist():
    for name in api.__all__:
        assert hasattr(api, name), f"Missing export: {name}"
