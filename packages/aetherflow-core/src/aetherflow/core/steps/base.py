from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Dict, Optional

# Step statuses used by the runner/state.
STEP_SUCCESS = "SUCCESS"
STEP_SKIPPED = "SKIPPED"


@dataclass
class StepResult:
    """Structured step outcome.

    Backwards compatible: if a step returns a plain dict from `run()`, the runner
    treats it as SUCCESS with that dict as its output.
    """

    status: str = STEP_SUCCESS
    output: Dict[str, Any] | None = None
    reason: Optional[str] = None

    def as_output(self) -> Dict[str, Any]:
        out = dict(self.output or {})
        if self.reason:
            out.setdefault("reason", self.reason)
        return out


class Step(abc.ABC):
    required_inputs: set[str] = set()

    def __init__(self, step_id: str, inputs: Dict[str, Any], ctx, job_id: str):
        self.id = step_id
        self.inputs = inputs
        self.ctx = ctx
        self.job_id = job_id

    def validate(self):
        missing = [k for k in self.required_inputs if k not in self.inputs]
        if missing:
            raise ValueError(f"Step {self.id} missing inputs: {missing}")

    @abc.abstractmethod
    def run(self) -> Dict[str, Any]:
        raise NotImplementedError
