from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
from aetherflow.core.api import Step, register_step

@register_step("excel_validate_template")
class ExcelValidateTemplate(Step):
    required_inputs = {"template_path", "required_names"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        try:
            import openpyxl
        except Exception as e:
            raise RuntimeError("openpyxl is required (install aetherflow-core[excel] or [reports])") from e

        job_dir = self.ctx.artifacts_dir(self.job_id)
        tp = Path(str(self.inputs["template_path"]))
        if not tp.is_absolute():
            tp = (job_dir / tp).resolve()
        wb = openpyxl.load_workbook(tp)
        defined = set(wb.defined_names.definedName)
        missing = [n for n in self.inputs["required_names"] if n not in defined]
        if missing:
            raise ValueError(f"Template missing named ranges: {missing}")
        return {"template_ok": True}
