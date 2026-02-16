from __future__ import annotations
from pathlib import Path
from aetherflow.core.api import ConnectorBase, ConnectorInit, register_connector

@register_connector(kind="smb", driver="smb-local")
class SMBLocal(ConnectorBase):
    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self.base_dir = Path((init.config or {}).get("base_dir", ".")).resolve()

    def put_file(self, local_path: str, remote_dir: str):
        dest_dir = (self.base_dir / remote_dir).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        lp = Path(local_path)
        (dest_dir / lp.name).write_bytes(lp.read_bytes())
