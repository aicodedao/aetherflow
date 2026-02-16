from __future__ import annotations

import re

from aetherflow.core.api import ConnectorBase, ConnectorInit, ConnectorError, register_connector, require

_DRIVE_RE = re.compile(r"^[A-Za-z]:(?:[\\/].*)?$")
_UNC_RE = re.compile(r"^\\\\[^\\\/]+\\[^\\\/]+(?:[\\\/].*)?$")  # \\host\share\...


@register_connector(kind="smb", driver="smb-pysmb")
class SMBPySMB(ConnectorBase):
    def __init__(self, init: ConnectorInit):
        super().__init__(init)
        self.cfg = init.config or {}
        self.options = init.options or {}
        self._conn = None

    def connect(self):
        SMBConnection = require("smb.SMBConnection:SMBConnection")
        try:
            self._conn = SMBConnection(
                self.cfg.get("username", ""),
                self.cfg.get("password", ""),
                "aetherflow",
                self.cfg.get("server", ""),
                use_ntlm_v2=True,
                is_direct_tcp=True,
            )
            server = self.cfg["server"]
            port = int(self.cfg.get("port", 445))
            if not self._conn.connect(server, port):
                raise ConnectorError("SMB connect returned False")
        except Exception as e:
            raise ConnectorError(f"SMB connect failed: {e}") from e

    def close(self):
        try:
            if self._conn:
                self._conn.close()
        finally:
            self._conn = None

    def _split_share_path(self, p: str) -> tuple[str, str]:
        """Return (share, path_in_share).
        Supported input forms:
          - "dir/file.txt" (uses config.share)
          - "/dir/file.txt" (uses config.share)
          - "SHARE:/dir/file.txt" (overrides share)
          - "A:\\dir\\file.txt" or "A:/dir/file.txt" (drive prefix stripped; uses config.share)
          - "\\\\host\\SHARE\\dir\\file.txt" (UNC; share inferred from path, unless overridden)
        """
        share = self.cfg.get("share")
        raw = str(p).strip()

        # 1) UNC full path: \\host\SHARE\dir\file
        if _UNC_RE.match(raw):
            # \\host\SHARE\rest...
            parts = raw.lstrip("\\").split("\\", 2)  # host, share, rest
            if len(parts) >= 2:
                unc_share = parts[1]
                rest = parts[2] if len(parts) == 3 else ""
                # If caller didn't specify share explicitly, infer from UNC
                if not share:
                    share = unc_share
                raw = rest

        # 2) Explicit share override: SHARE:/path or SHARE:\path
        # Accept both ":/" and ":\"
        if ":/" in raw or ":\\" in raw:
            if ":/" in raw:
                prefix, rest = raw.split(":/", 1)
                sep = "/"
            else:
                prefix, rest = raw.split(":\\", 1)
                sep = "\\"
            # Only treat as share override if prefix looks like a share name,
            # AND prefix is not a Windows drive letter (C, D, ...)
            if prefix and all(ch.isalnum() or ch in "_.-" for ch in prefix) and len(prefix) != 1:
                share = prefix
                raw = rest
            else:
                # drive letter case handled below
                raw = prefix + ":" + (sep + rest if rest else "")

        # 3) Drive letter path: A:\dir\file or A:/dir/file -> strip "A:\"
        if _DRIVE_RE.match(raw):
            raw = raw[2:]  # drop "A:"
            raw = raw.lstrip("/\\")  # drop leading slash after drive

        if not share:
            raise ConnectorError(
                f"smb-pysmb path requires a share (set config.share or use 'SHARE:/path') {p}"
            )

        path_in_share = raw.lstrip("/\\").replace("\\", "/")
        return str(share), path_in_share

    def put_file(self, local_path: str, remote_path: str):
        if not self._conn:
            self.connect()

        share, p = self._split_share_path(remote_path)
        with open(local_path, "rb") as f:
            self._conn.storeFile(share, f"/{p}", f)

