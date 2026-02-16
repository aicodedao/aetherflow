from __future__ import annotations

from typing import List

from aetherflow.core.api import ConnectorBase, ConnectorInit, ConnectorError, register_connector, RemoteFileMeta, \
    require


@register_connector(kind="sftp", driver="sftp-moveit")
class SFTPMoveIt(ConnectorBase):
    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self.cfg = init.config or {}
        self.options = init.options or {}
        self._client = None
        self._sftp = None

    def connect(self):
        paramiko = require("paramiko")
        host = self.cfg["host"]
        port = int(self.cfg.get("port", 22))
        user = self.cfg["user"]
        password = self.cfg.get("password")
        timeout = int(self.options.get("timeout", 30) or 30)
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(hostname=host, port=port, username=user, password=password, timeout=timeout)
            self._client = client
            self._sftp = client.open_sftp()
        except Exception as e:
            raise ConnectorError(f"SFTP connect failed: {e}") from e

    def close(self):
        try:
            if self._sftp:
                self._sftp.close()
        finally:
            if self._client:
                self._client.close()
        self._sftp = None
        self._client = None

    def listdir(self, remote_dir: str) -> List[RemoteFileMeta]:
        """
            sftp: paramiko.SFTPClient
            remote_dir: "/path/on/server"
        """
        stat = require("stat")
        out: list[RemoteFileMeta] = []
        if not self._sftp:
            self.connect()
        for attr in self._sftp.listdir_attr(remote_dir):
            name = attr.filename
            if name in (".", ".."):
                continue
            is_dir = stat.S_ISDIR(attr.st_mode)
            out.append(
                RemoteFileMeta(
                    path=f"{remote_dir.rstrip('/')}/{name}",
                    name=name,
                    is_dir=is_dir,
                    size=None if is_dir else attr.st_size,
                    mtime=int(attr.st_mtime) if attr.st_mtime else None,
                )
            )
        return out

    def get(self, remote_path: str, local_path: str) -> None:
        if not self._sftp:
            self.connect()
        self._sftp.get(remote_path, local_path)

    def delete(self, remote_path: str, is_dir: bool = False) -> None:
        import errno
        if not self._sftp:
            self.connect()
        try:
            self._sftp.stat(remote_path)
            if is_dir:
                self._sftp.rmdir(remote_path)
            else:
                self._sftp.remove(remote_path)
        except FileNotFoundError:
            # Already gone => idempotent success
            return
        except OSError as e:
            if getattr(e, "errno", None) == errno.ENOENT:
                return
            raise


