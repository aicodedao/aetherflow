from __future__ import annotations

from typing import Any, Dict

from aetherflow.core.api import Step, register_step, require


@register_step("excel_validate_template_custom")
class ExcelValidateTemplateCustom(Step):
    required_inputs = {"template_path", "required_names"}

    def _iter_target_sheets(self, wb, sheet_name: str | None):
        if sheet_name:
            if sheet_name not in wb.sheetnames:
                raise ValueError(f"Sheet not found: {sheet_name}")
            return [wb[sheet_name]]
        else:
            return list(wb.worksheets)

    def run(self) -> Dict[str, Any]:
        self.validate()
        openpyxl = require("openpyxl")
        json = require("json")
        Path = require("pathlib:Path")

        job_dir = self.ctx.artifacts_dir(self.job_id)
        tp = Path(str(self.inputs["template_path"]))
        if not tp.is_absolute():
            tp = (job_dir / tp).resolve()

        wb = openpyxl.load_workbook(tp, data_only=True)
        # ---- 1) Collect named ranges ----
        defined_names = set(wb.defined_names.keys())
        # ---- 2) Collect anchor text values in all sheets ----
        anchor_values = set()
        wss = self._iter_target_sheets(wb=wb, sheet_name=self.inputs.get("sheet"))
        for ws in wss:
            for row in ws.iter_rows(values_only=True):
                for v in row:
                    if isinstance(v, str):
                        anchor_values.add(v.strip())
        # ---- 3) Normalize required list ----
        req = self.inputs["required_names"]
        if isinstance(req, str):
            try:
                req = json.loads(req)
            except Exception:
                req = [req]
        if not isinstance(req, list):
            raise ValueError(f"required_names must be a list of strings {req}")
        missing = []
        found_named = []
        found_anchor = []
        for name in req:
            if name in defined_names:
                found_named.append(name)
            elif name in anchor_values:
                found_anchor.append(name)
            else:
                missing.append(name)
        if missing:
            raise ValueError(f"Template missing named ranges or anchor cells: {missing} {req}")
        return {
            "template_ok": True,
            "found_named_ranges": sorted(found_named),
            "found_anchor_cells": sorted(found_anchor),
        }
