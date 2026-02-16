from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Protocol, runtime_checkable



@runtime_checkable
class ConnectorBase(Protocol):
    """
    Public connector contract.

    A connector is a thin, reusable wrapper around a concrete transport/driver
    (DB driver, HTTP client, SFTP session, etc.). Steps may use its primitives,
    and power-users can request the underlying session/connection/client.

    Connectors should:
      - be safe to instantiate multiple times
      - not mutate global state
      - honor pooling/timeouts/retry options from resource config
      - expose a best-effort lifecycle via close() / context manager
    """

    name: str
    kind: str
    driver: str
    config: Dict[str, Any]
    options: Dict[str, Any]

    def close(self) -> None: ...

    def __enter__(self): ...
    def __exit__(self, exc_type, exc, tb) -> None: ...


@dataclass
class ConnectorInit:
    name: str
    kind: str
    driver: str
    config: Dict[str, Any]
    options: Dict[str, Any]
    ctx: Any | None = None
