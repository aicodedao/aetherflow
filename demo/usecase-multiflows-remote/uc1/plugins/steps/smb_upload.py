from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from aetherflow.core.api import Step, register_step


@register_step("smb_upload_files_custom")
class SMBUploadFilesCustom(Step):
    required_inputs = {"resource", "local_files", "remote_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        smb = self.ctx.connectors[self.inputs["resource"]]
        remote_dir = self.inputs["remote_dir"]
        local_files: List[str] = self.inputs.get("local_files") or []
        uploaded = []
        for lf in local_files:
            lfp = Path(lf)
            if not lfp.is_absolute():
                lfp = (self.ctx.artifacts_dir(self.job_id) / lfp).resolve()
            smb.put_file(lfp, f"{remote_dir}/{lfp.name}")
            uploaded.append(lfp)
        return {"uploaded": uploaded, "remote_dir": remote_dir}
