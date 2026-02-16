from __future__ import annotations

from typing import Any, Dict, Tuple, Type

from aetherflow.core.connectors.base import ConnectorBase, ConnectorInit


class ConnectorRegistry:
    """
    Registry + factory for connectors.

    Supports decorator registration:
        @registry.register("db", "sqlalchemy")
        class SQLAlchemyDB: ...

    And factory instantiation that binds a resolved resource:
        conn = registry.create(name="db_main", kind="db", driver="sqlalchemy", config=..., options=..., ctx=...)
    """

    def __init__(self) -> None:
        self._items: Dict[Tuple[str, str], Type] = {}

    def register(self, kind: str, driver: str):
        def deco(cls):
            self._items[(kind, driver)] = cls
            return cls
        return deco

    def get(self, kind: str, driver: str):
        key = (kind, driver)
        if key not in self._items:
            avail = sorted([f"{k}:{d}" for (k, d) in self._items.keys()])
            raise KeyError(f"Unknown connector: {kind}:{driver}. Loaded: {avail}")
        return self._items[key]

    def list(self) -> list[str]:
        return sorted([f"{k}:{d}" for (k, d) in self._items.keys()])

    def create(self, *, name: str, kind: str, driver: str, config: dict, options: dict | None = None, ctx: Any | None = None) -> ConnectorBase:
        Cls = self.get(kind, driver)
        opts = options or {}

        # Prefer a consistent init signature via ConnectorInit if supported,
        # but keep backwards compatibility with older connector classes.
        try:
            return Cls(ConnectorInit(name=name, kind=kind, driver=driver, config=config, options=opts, ctx=ctx))
        except TypeError:
            # Legacy: Cls(config, options)
            return Cls(config, opts)


# Singleton registry used by core + plugins
REGISTRY = ConnectorRegistry()


# Back-compat module-level helpers
def register_connector(kind: str, driver: str):
    return REGISTRY.register(kind, driver)


def get_connector(kind: str, driver: str):
    return REGISTRY.get(kind, driver)


def list_connectors() -> list[str]:
    return REGISTRY.list()
