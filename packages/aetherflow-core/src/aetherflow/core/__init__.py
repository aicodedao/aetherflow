"""Aetherflow core package.

Public entrypoints:
- aetherflow.core.api: stable API surface for integrations/plugins
- aetherflow.core.runner.run_flow: run a flow programmatically

Internal modules may change without notice.
"""

from __future__ import annotations

# Strict architecture enforcement (default ON; set AETHERFLOW_STRICT_ARCH=0 to disable).
from aetherflow.core._architecture_guard import assert_architecture as _assert_architecture

_assert_architecture()

# Ensure built-in steps/connectors are registered on import.
from aetherflow.core.builtins import register as _register  # noqa: F401

from aetherflow.core.runner import run_flow

__all__ = ["run_flow"]
