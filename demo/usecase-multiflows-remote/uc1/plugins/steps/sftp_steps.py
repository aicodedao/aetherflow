from __future__ import annotations

import fnmatch
from dataclasses import replace
from typing import Any, Dict, List

from aetherflow.core.api import Step, StepResult, STEP_SKIPPED, STEP_SUCCESS, register_step, RemoteFileMeta, \
    ConnectorError


@register_step("sftp_list_files_custom")
class SFTPListFilesCustom(Step):
    required_inputs = {"resource", "remote_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        res = self.ctx.connectors[self.inputs["resource"]]
        pattern = self.inputs.get("pattern", "*")
        recursive = self.inputs.get("recursive", False)
        base_path = self.inputs["remote_dir"].rstrip("/") or "/"
        items: List[RemoteFileMeta] = []

        def _walk(cur: str, recursive: bool):
            try:
                entries = res.listdir(cur)
                for e in entries:
                    # guard path
                    p = e.path or ""
                    if e.is_dir and recursive:
                        if p and p != cur:   # avoid accidental self-loop
                            _walk(p, recursive)
                        continue
                    if not fnmatch.fnmatch(e.name, pattern):
                        continue
                    rel = p[len(base_path) + 1 :] if (base_path != "/" and p.startswith(base_path + "/")) else (
                        p[1:] if (base_path == "/" and p.startswith("/")) else p
                    )
                    items.append(replace(e, rel_path=rel))
            except Exception as e:
                raise ConnectorError(f"SFTPListFilesCustom list failed: {cur} {recursive} {e}") from e

        _walk(base_path, recursive)
        count = len(items)
        min_count = int(self.inputs.get("min_count", 1))
        if count < min_count:
            return StepResult(
                status=STEP_SKIPPED,
                output={"has_data": False, "count": count, "files": []},
                reason=f"count({count}) < min_count({min_count})",
            )
        return StepResult(
            status=STEP_SUCCESS,
            output={"has_data": True, "count": count, "files": sorted(items, key=lambda x: x.rel_path)}
        )

@register_step("sftp_download_files_custom")
class SFTPDownloadFilesCustom(Step):
    required_inputs = {"resource", "files", "dest_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        res = self.ctx.connectors[self.inputs["resource"]]
        job_dir = self.ctx.artifacts_dir(self.job_id)
        dest_dir = (job_dir / self.inputs["dest_dir"]).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)
        local_files = []
        for m in (self.inputs.get("files") or []):
            rel = m.rel_path.lstrip("/")
            dest = dest_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            res.get(m.path, str(dest))
            local_files.append(str(dest))
        return {"local_files": local_files, "dest_dir": str(dest_dir)}

@register_step("sftp_delete_files_custom")
class SFTPDeleteFilesCustom(Step):
    required_inputs = {"resource", "files"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        res = self.ctx.connectors[self.inputs["resource"]]
        for m in (self.inputs.get("files") or []):
            res.delete(m.path)
        return {"is_deleted": True}
