from __future__ import annotations
from pathlib import Path
from typing import List
from aetherflow.core.api import ConnectorBase, ConnectorInit, register_connector, ConnectorError

@register_connector(kind="sftp", driver="sftp-local")
class SFTPLocal(ConnectorBase):
    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self.base_dir = Path((init.config or {}).get("base_dir", ".")).resolve()

    def listdir(self, remote_dir: str) -> List[str]:
        d = (self.base_dir / remote_dir).resolve()
        if not d.exists():
            return []
        return [p.name for p in d.iterdir() if p.is_file()]

    def get(self, remote_path: str, local_path: str) -> None:
        src = (self.base_dir / remote_path).resolve()
        if not src.exists():
            raise ConnectorError(f"Local SFTP path not found: {src}")
        Path(local_path).write_bytes(src.read_bytes())
