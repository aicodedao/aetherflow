from __future__ import annotations

from typing import Any, Dict

from aetherflow.core.api import Step, register_step


@register_step("local_transform_csv")
class LocalTransformCSV(Step):
    required_inputs = {"src_dir", "dst_dir"}
    def run(self) -> Dict[str, Any]:
        self.validate()
        job_dir = self.ctx.artifacts_dir(self.job_id)
        src = (job_dir / self.inputs["src_dir"]).resolve()
        dst = (job_dir / self.inputs["dst_dir"]).resolve()
        dst.mkdir(parents=True, exist_ok=True)

        changed = 0
        for p in src.rglob("*"):
            if p.is_dir():
                continue
            rel = p.relative_to(src)
            out = dst / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if p.suffix.lower() == ".csv":
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                if lines:
                    lines[0] = lines[0].upper()
                out.write_text("\\n".join(lines), encoding="utf-8")
                changed += 1
            else:
                out.write_bytes(p.read_bytes())
        return {"dst_dir": str(dst), "csv_transformed": changed}
