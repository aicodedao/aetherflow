from __future__ import annotations

import zipfile
from typing import Any, Dict

from aetherflow.core.api import Step, register_step


@register_step("demo_prepare_inbox")
class DemoPrepareInbox(Step):
    required_inputs = {"out_dir", "zip_name"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        job_dir = self.ctx.artifacts_dir(self.job_id)
        out_dir = (job_dir / self.inputs["out_dir"]).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        csv_path = out_dir / "sample.csv"
        csv_path.write_text("col1,col2\\n1,hello\\n2,world\\n", encoding="utf-8")
        zip_path = out_dir / self.inputs["zip_name"]
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(csv_path, arcname="sample.csv")
        csv_path.unlink(missing_ok=True)
        return {"demo_zip": str(zip_path)}
