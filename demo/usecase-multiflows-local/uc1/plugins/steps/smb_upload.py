from __future__ import annotations

from typing import Any, Dict, List

from aetherflow.core.api import Step, register_step


@register_step("smb_upload_files")
class SMBUploadFiles(Step):
    required_inputs = {"resource", "local_files", "remote_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        smb = self.ctx.connectors[self.inputs["resource"]]
        remote_dir = self.inputs["remote_dir"]
        local_files: List[str] = self.inputs.get("local_files") or []
        uploaded = []
        for lp in local_files:
            smb.put_file(lp, remote_dir)
            uploaded.append(lp)
        return {"uploaded": uploaded, "remote_dir": remote_dir}
