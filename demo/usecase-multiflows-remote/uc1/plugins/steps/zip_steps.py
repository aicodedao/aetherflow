from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from aetherflow.core.api import Step, register_step


@register_step("fs_find_zipfiles")
class FSFindFiles(Step):
    required_inputs = {"src_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        base = Path(str(self.inputs["src_dir"]))
        if not base.is_absolute():
            base = (self.ctx.artifacts_dir(self.job_id) / base).resolve()
        pattern = self.inputs.get("pattern", "*.zip")
        recursive = bool(self.inputs.get("recursive", True))

        if not base.exists():
            return {"zip_files": []}

        it = base.rglob(pattern) if recursive else base.glob(pattern)
        files = [str(p) for p in it if p.is_file()]
        files.sort()
        return {"zip_files": files, "src_dir": str(base)}


