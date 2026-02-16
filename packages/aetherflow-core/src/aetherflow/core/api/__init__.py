"""Public, stable API surface for Aetherflow.

If you're writing plugins or integrating Aetherflow into your own codebase,
import from **`aetherflow.core.api`**.

Everything outside this package is considered internal and may change without
notice, even in minor releases.
"""

from __future__ import annotations

# Connector contracts
from aetherflow.core.connectors import require, require_attr
from aetherflow.core.connectors.base import ConnectorBase, ConnectorInit
# Runtime context
from aetherflow.core.context import RunContext, new_run_id
# Common exceptions
from aetherflow.core.exception import ConnectorError
from aetherflow.core.registry.connectors import get_connector, list_connectors, register_connector
# Registries (steps/connectors) + resource resolver
from aetherflow.core.registry.steps import get_step, list_steps, register_step
# Settings
from aetherflow.core.runtime.settings import Settings
# Flow specification (Pydantic models)
from aetherflow.core.spec import (
    CleanupPolicy,
    FlowMetaSpec,
    FlowSpec,
    JobSpec,
    LocksSpec,
    LockScope,
    ResourceSpec,
    StateSpec,
    StepSpec,
    WorkspaceSpec,
    RemoteFileMeta,
)
# Step contract
from aetherflow.core.steps.base import STEP_SKIPPED, STEP_SUCCESS, Step, StepResult

__all__ = [
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
