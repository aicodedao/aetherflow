from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any, Dict, Optional

from aetherflow.core.runtime.settings import Settings

log = logging.getLogger("aetherflow.core.bundle")


class MetricsSink:
    """Optional metrics sink.

    Users can provide a module via AETHERFLOW_METRICS_MODULE exposing METRICS: MetricsSink.
    This is intentionally tiny: it gives production users a stable hook point without
    forcing a dependency on any metrics stack.
    """

    def on_run_start(self, *, flow_id: str, run_id: str) -> None:  # pragma: no cover
        return None

    def on_run_end(self, *, flow_id: str, run_id: str, summary: dict) -> None:  # pragma: no cover
        return None

    def on_job_start(self, *, flow_id: str, run_id: str, job_id: str) -> None:  # pragma: no cover
        return None

    def on_job_end(self, *, flow_id: str, run_id: str, job_id: str, status: str, duration_ms: int) -> None:  # pragma: no cover
        return None

    def on_step_start(self, *, flow_id: str, run_id: str, job_id: str, step_id: str, step_type: str) -> None:  # pragma: no cover
        return None

    def on_step_end(self, *, flow_id: str, run_id: str, job_id: str, step_id: str, step_type: str, status: str, duration_ms: int) -> None:  # pragma: no cover
        return None


def load_metrics_sink(settings: Settings) -> MetricsSink:
    mod = settings.metrics_module
    if not mod:
        return MetricsSink()
    m = import_module(mod)
    sink = getattr(m, "METRICS", None)
    if sink is None:
        raise AttributeError(f"{mod} must expose METRICS")
    return sink


def _now_ms() -> int:
    return int(time.time() * 1000)


def _dur_ms(t0: float, t1: float) -> int:
    return int((t1 - t0) * 1000)


def log_event(logger: logging.Logger, *, settings: Settings, level: int, event: str, **fields: Any) -> None:
    """Emit an event log.

    - text format: one-liner `event key=value ...`
    - json format: one JSON object per line
    """
    if settings.log_format.lower() == "json":
        payload = {"ts_ms": _now_ms(), "event": event, **fields}
        logger.log(level, json.dumps(payload, ensure_ascii=False, default=str))
        return

    # text
    parts = [event]
    for k, v in fields.items():
        parts.append(f"{k}={v}")
    logger.log(level, " ".join(parts))


@dataclass
class StepSummary:
    step_id: str
    step_type: str
    status: str
    duration_ms: int


@dataclass
class JobSummary:
    job_id: str
    status: str
    duration_ms: int
    steps: list[StepSummary] = field(default_factory=list)
    skip_reason: str | None = None


@dataclass
class RunSummary:
    flow_id: str
    run_id: str
    status_counts: Dict[str, int]
    duration_ms: int
    jobs: list[JobSummary] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "flow_id": self.flow_id,
            "run_id": self.run_id,
            "duration_ms": self.duration_ms,
            "status_counts": dict(self.status_counts),
            "jobs": [
                {
                    "job_id": j.job_id,
                    "status": j.status,
                    "duration_ms": j.duration_ms,
                    "skip_reason": j.skip_reason,
                    "steps": [
                        {
                            "step_id": s.step_id,
                            "step_type": s.step_type,
                            "status": s.status,
                            "duration_ms": s.duration_ms,
                        }
                        for s in j.steps
                    ],
                }
                for j in self.jobs
            ],
        }


class RunObserver:
    """Collects run/job/step timings and emits end-of-run summary."""

    def __init__(self, *, settings: Settings, logger: logging.Logger, flow_id: str, run_id: str):
        self.settings = settings
        self.logger = logger
        self.flow_id = flow_id
        self.run_id = run_id
        self._t_run0: float | None = None
        self._job_t0: dict[str, float] = {}
        self._step_t0: dict[tuple[str, str], float] = {}
        self._jobs: dict[str, JobSummary] = {}
        self.metrics = load_metrics_sink(settings)

    def run_start(self, *, yaml_path: str) -> None:
        self._t_run0 = time.perf_counter()
        log_event(self.logger, settings=self.settings, level=logging.INFO, event="run_start", flow_id=self.flow_id, run_id=self.run_id, yaml=yaml_path)
        try:
            self.metrics.on_run_start(flow_id=self.flow_id, run_id=self.run_id)
        except Exception:
            # Metrics must never break the run.
            log.warning("RunObserver.runstart failed", exc_info=True)
        pass

    def job_start(self, *, job_id: str) -> None:
        self._job_t0[job_id] = time.perf_counter()
        self._jobs[job_id] = JobSummary(job_id=job_id, status="RUNNING", duration_ms=0)
        log_event(self.logger, settings=self.settings, level=logging.INFO, event="job_start", flow_id=self.flow_id, run_id=self.run_id, job_id=job_id)
        try:
            self.metrics.on_job_start(flow_id=self.flow_id, run_id=self.run_id, job_id=job_id)
        except Exception:
            log.warning("RunObserver.runstart failed", exc_info=True)
        pass

    def step_start(self, *, job_id: str, step_id: str, step_type: str) -> None:
        self._step_t0[(job_id, step_id)] = time.perf_counter()
        log_event(self.logger, settings=self.settings, level=logging.INFO, event="step_start", flow_id=self.flow_id, run_id=self.run_id, job_id=job_id, step_id=step_id, step_type=step_type)
        try:
            self.metrics.on_step_start(flow_id=self.flow_id, run_id=self.run_id, job_id=job_id, step_id=step_id, step_type=step_type)
        except Exception:
            log.warning("RunObserver.runstart failed", exc_info=True)
        pass

    def step_end(self, *, job_id: str, step_id: str, step_type: str, status: str) -> None:
        t0 = self._step_t0.pop((job_id, step_id), None)
        dur = _dur_ms(t0, time.perf_counter()) if t0 is not None else 0
        js = self._jobs.get(job_id)
        if js is not None:
            js.steps.append(StepSummary(step_id=step_id, step_type=step_type, status=status, duration_ms=dur))
        log_event(self.logger, settings=self.settings, level=logging.INFO, event="step_end", flow_id=self.flow_id, run_id=self.run_id, job_id=job_id, step_id=step_id, step_type=step_type, status=status, duration_ms=dur)
        try:
            self.metrics.on_step_end(flow_id=self.flow_id, run_id=self.run_id, job_id=job_id, step_id=step_id, step_type=step_type, status=status, duration_ms=dur)
        except Exception:
            log.warning("RunObserver.runstart failed", exc_info=True)
        pass

    def job_end(self, *, job_id: str, status: str, skip_reason: Optional[str] = None) -> None:
        t0 = self._job_t0.pop(job_id, None)
        dur = _dur_ms(t0, time.perf_counter()) if t0 is not None else 0
        js = self._jobs.get(job_id)
        if js is not None:
            js.status = status
            js.duration_ms = dur
            js.skip_reason = skip_reason
        log_event(self.logger, settings=self.settings, level=logging.INFO, event="job_end", flow_id=self.flow_id, run_id=self.run_id, job_id=job_id, status=status, duration_ms=dur, skip_reason=skip_reason)
        try:
            self.metrics.on_job_end(flow_id=self.flow_id, run_id=self.run_id, job_id=job_id, status=status, duration_ms=dur)
        except Exception:
            log.warning("RunObserver.runstart failed", exc_info=True)
        pass

    def run_end(self, *, status_counts: Dict[str, int]) -> RunSummary:
        t0 = self._t_run0
        dur = _dur_ms(t0, time.perf_counter()) if t0 is not None else 0
        summary = RunSummary(flow_id=self.flow_id, run_id=self.run_id, duration_ms=dur, status_counts=status_counts, jobs=list(self._jobs.values()))
        log_event(self.logger, settings=self.settings, level=logging.INFO, event="run_summary", **summary.as_dict())
        try:
            self.metrics.on_run_end(flow_id=self.flow_id, run_id=self.run_id, summary=summary.as_dict())
        except Exception:
            log.warning("RunObserver.runstart failed", exc_info=True)
        return summary
