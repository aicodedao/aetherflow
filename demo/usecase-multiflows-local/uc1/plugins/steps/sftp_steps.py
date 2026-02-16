from __future__ import annotations
import fnmatch
from pathlib import Path
from typing import Any, Dict, List
from aetherflow.core.api import Step, register_step

@register_step("sftp_list_files")
class SFTPListFiles(Step):
    required_inputs = {"resource", "remote_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        res = self.ctx.connectors[self.inputs["resource"]]
        remote_dir = self.inputs["remote_dir"]
        pattern = self.inputs.get("pattern", "*")
        names = res.listdir(remote_dir)
        files = [f"{remote_dir.rstrip('/')}/{n}" for n in names if fnmatch.fnmatch(n, pattern)]
        return {"files": files}

@register_step("sftp_download_files")
class SFTPDownloadFiles(Step):
    required_inputs = {"resource", "files", "dest_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        res = self.ctx.connectors[self.inputs["resource"]]
        job_dir = self.ctx.artifacts_dir(self.job_id)
        dest_dir = (job_dir / self.inputs["dest_dir"]).resolve()
        dest_dir.mkdir(parents=True, exist_ok=True)

        files: List[str] = self.inputs.get("files") or []
        local_files = []
        for rp in files:
            name = Path(rp).name
            lp = dest_dir / name
            res.get(rp, str(lp))
            local_files.append(str(lp))
        return {"local_files": local_files, "dest_dir": str(dest_dir)}
