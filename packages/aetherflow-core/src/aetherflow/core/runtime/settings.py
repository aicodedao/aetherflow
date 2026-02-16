from __future__ import annotations

import os
from importlib import import_module
from typing import List

from pydantic import BaseModel, Field


class Settings(BaseModel):
    # Defaults are static. Use load_settings(env=...) to read from an env snapshot.
    work_root: str = "/tmp/work"
    state_root: str = "/tmp/state"

    plugin_paths: List[str] = Field(default_factory=list)
    plugin_strict: bool = True
    strict_templates: bool = True
    log_level: str = "INFO"

    # Observability
    # - log_format: "text" (default) or "json". When json, aetherflow logs emit a single JSON
    #   object per line, suitable for log aggregation.
    log_format: str = "text"

    # Optional metrics sink module (exposes METRICS: MetricsSink)
    metrics_module: str | None = None

    # Connector caching
    # - connector_cache_default: "run" (cache within a single flow run)
    # - "process" reuses connectors across runs in the same Python process (good for pooled DB engines)
    # - "none" disables caching by default
    connector_cache_default: str = "run"
    connector_cache_disabled: bool = False

    # Secrets hook: load decode/expand_env from module or file path
    secrets_module: str | None = None
    secrets_path: str | None = None



    @classmethod
    def from_env(cls, env: dict[str, str], overrides: dict | None = None) -> "Settings":
        """Build Settings from an explicit env snapshot (does not read os.environ)."""
        def g(key: str, default: str | None = None) -> str | None:
            return env.get(key, default)  # type: ignore[return-value]

        data = {
            "work_root": g("AETHERFLOW_WORK_ROOT", "/tmp/work"),
            "state_root": g("AETHERFLOW_STATE_ROOT", "/tmp/state"),
            "plugin_paths": [p for p in (g("AETHERFLOW_PLUGIN_PATHS", "") or "").split(",") if p],
            "plugin_strict": (g("AETHERFLOW_PLUGIN_STRICT", "true") or "true").lower() == "true",
            "strict_templates": (g("AETHERFLOW_STRICT_TEMPLATES", "true") or "true").lower() == "true",
            "log_level": g("AETHERFLOW_LOG_LEVEL", "INFO"),
            "log_format": g("AETHERFLOW_LOG_FORMAT", "text"),
            "metrics_module": g("AETHERFLOW_METRICS_MODULE") or None,
            "connector_cache_default": g("AETHERFLOW_CONNECTOR_CACHE_DEFAULT", "run"),
            "connector_cache_disabled": (g("AETHERFLOW_CONNECTOR_CACHE_DISABLED", "false") or "false").lower() == "true",
            "secrets_module": g("AETHERFLOW_SECRETS_MODULE") or None,
            "secrets_path": g("AETHERFLOW_SECRETS_PATH") or None,
            "enterprise_mode": g("AETHERFLOW_MODE_ENTERPRISE") or False,
            "sandbox": g("AETHERFLOW_STRICT_SANDBOX") or True,
        }
        if overrides:
            data.update(overrides)
        return cls(**data)


def load_settings(overrides: dict | None = None, *, env: dict[str, str] | None = None) -> Settings:
    """Load settings from (1) env snapshot, (2) optional settings module, (3) explicit overrides.

    If env is not provided, we build a snapshot from os.environ. This keeps the codebase
    deterministic while preserving backward-compatible behavior.
    """
    env2 = {k: str(v) for k, v in os.environ.items()} if env is None else env
    s = Settings.from_env(env2)
    mod = env2.get("AETHERFLOW_SETTINGS_MODULE")
    if mod:
        m = import_module(mod)
        data = getattr(m, "SETTINGS", {})
        if not isinstance(data, dict):
            raise TypeError("AETHERFLOW_SETTINGS_MODULE must expose SETTINGS: dict")
        s = s.model_copy(update=data)
    if overrides:
        s = s.model_copy(update=overrides)
    return s
