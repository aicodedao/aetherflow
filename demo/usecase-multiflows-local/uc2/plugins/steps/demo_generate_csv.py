from __future__ import annotations
import csv
from pathlib import Path
from typing import Any, Dict, List
from aetherflow.core.api import Step, register_step

@register_step("demo_generate_csv")
class DemoGenerateCSV(Step):
    required_inputs = {"output", "header", "rows"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        job_dir = self.ctx.artifacts_dir(self.job_id)
        out = Path(job_dir / self.inputs["output"]).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        header: List[str] = self.inputs["header"]
        rows: List[List[Any]] = self.inputs["rows"]
        with open(out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(header)
            for r in rows:
                w.writerow(r)
        return {"artifact_path": str(out)}
