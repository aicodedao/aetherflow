from __future__ import annotations

import threading
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from aetherflow.core.connectors.base import ConnectorBase
from aetherflow.core.registry.connectors import REGISTRY


# Process-wide cache for connectors (opt-in via cache="process").
_PROCESS_CACHE: Dict[Tuple[str, str, str], ConnectorBase] = {}
_PROCESS_LOCK = threading.Lock()
log = logging.getLogger('aetherflow.core.connectors.manager')


def _cache_key(kind: str, driver: str, name: str) -> Tuple[str, str, str]:
    return (kind, driver, name)


@dataclass
class Connectors:
    """Connector accessor with caching + opt-out.

    Access patterns:
        db = ctx.connectors.db("db_main")
        with db.connect() as conn: ...

        # Generic
        c = ctx.connectors.get(kind="rest", name="api")

        # Disable cache per-call
        c = ctx.connectors.get(kind="rest", name="api", cache="none")

    Caching policy resolution order:
        1) per-call override via cache=...
        2) resource config key "cache" ("run"|"process"|"none")
        3) Settings.connector_cache_disabled -> "none"
        4) Settings.connector_cache_default
    """

    ctx: Any
    resources: Dict[str, dict]
    settings: Any

    # Run-scoped cache
    _run_cache: Dict[Tuple[str, str, str], ConnectorBase] = None  # type: ignore

    def __post_init__(self) -> None:
        self._run_cache = {}

    def _policy_for(self, resource: dict, cache: Optional[str]) -> str:
        if cache:
            return cache
        if self.settings.connector_cache_disabled:
            return "none"
        pol = (resource.get("cache") or resource.get("options", {}).get("cache") or "").strip().lower()
        if pol:
            return pol
        return str(getattr(self.settings, "connector_cache_default", "run")).strip().lower() or "run"

    def get(self, *, kind: str, name: str, cache: Optional[str] = None) -> ConnectorBase:
        if name not in self.resources:
            raise KeyError(f"Unknown resource: {name}. Known: {sorted(self.resources.keys())}")
        r = self.resources[name]
        if r["kind"] != kind:
            raise KeyError(f"Resource {name} is kind={r['kind']}, requested kind={kind}")
        driver = r["driver"]

        policy = self._policy_for(r, cache)
        key = _cache_key(kind, driver, name)

        if policy == "none":
            return REGISTRY.create(
                name=name,
                kind=kind,
                driver=driver,
                config=r["config"],
                options=r.get("options") or {},
                ctx=self.ctx,
            )

        if policy == "process":
            with _PROCESS_LOCK:
                if key in _PROCESS_CACHE:
                    return _PROCESS_CACHE[key]
                inst = REGISTRY.create(
                    name=name,
                    kind=kind,
                    driver=driver,
                    config=r["config"],
                    options=r.get("options") or {},
                    ctx=self.ctx,
                )
                _PROCESS_CACHE[key] = inst
                return inst

        # Default: run
        if key in self._run_cache:
            return self._run_cache[key]
        inst = REGISTRY.create(
            name=name,
            kind=kind,
            driver=driver,
            config=r["config"],
            options=r.get("options") or {},
            ctx=self.ctx,
        )
        self._run_cache[key] = inst
        return inst

    # Convenience accessors
    def db(self, name: str, *, cache: Optional[str] = None):
        return self.get(kind="db", name=name, cache=cache)

    def rest(self, name: str, *, cache: Optional[str] = None):
        return self.get(kind="rest", name=name, cache=cache)

    def sftp(self, name: str, *, cache: Optional[str] = None):
        return self.get(kind="sftp", name=name, cache=cache)

    def smb(self, name: str, *, cache: Optional[str] = None):
        return self.get(kind="smb", name=name, cache=cache)

    def mail(self, name: str, *, cache: Optional[str] = None):
        return self.get(kind="mail", name=name, cache=cache)

    def archive(self, name: str, *, cache: Optional[str] = None):
        """Archive connector (zip/unzip abstraction)."""
        return self.get(kind="archive", name=name, cache=cache)

    # Back-compat: allow ctx.connectors["db_main"] usage
    def __getitem__(self, name: str) -> ConnectorBase:
        if name not in self.resources:
            raise KeyError(name)
        r = self.resources[name]
        return self.get(kind=r["kind"], name=name)

    def close_all(self) -> None:
        # Close run-scoped connectors. Process-scoped connectors remain alive.
        for conn in list(self._run_cache.values()):
            try:
                conn.close()
            except Exception as e:
                log.warning("connector close failed; continuing", exc_info=True)
        self._run_cache.clear()
