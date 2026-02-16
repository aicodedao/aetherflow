from pathlib import Path
import yaml

from aetherflow.scheduler.spec import SchedulerFileSpec
import aetherflow.scheduler.scheduler as sched_mod


class DummyScheduler:
    def __init__(self, timezone):
        self.timezone = timezone
        self.jobs = []
    def add_job(self, func, trigger, id, max_instances, coalesce, misfire_grace_time):
        self.jobs.append({"func": func, "id": id, "misfire": misfire_grace_time, "trigger": trigger})
    def start(self): pass
    def shutdown(self, wait=False): pass


def test_scheduler_registers_jobs_and_callable_runs(monkeypatch):
    repo_root = Path(__file__).resolve().parents[3]
    p = repo_root / "demo" / "usecase-singleflow" / "scheduler" / "scheduler.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = SchedulerFileSpec.model_validate(data)

    dummy = DummyScheduler(timezone=cfg.timezone)

    calls = []
    def fake_run_flow(flow_yaml, flow_job=None, bundle_manifest=None, allow_stale_bundle=False):
        calls.append(
            dict(
                flow_yaml=flow_yaml,
                flow_job=flow_job,
                bundle_manifest=bundle_manifest,
                allow_stale_bundle=allow_stale_bundle,
            )
        )

    # patch scheduler objects
    monkeypatch.setattr(sched_mod, "BackgroundScheduler", lambda timezone: dummy, raising=True)
    monkeypatch.setattr(sched_mod, "run_flow", fake_run_flow, raising=True)

    # patch infinite loop: stop after start()
    def fake_sleep(_): raise SystemExit
    monkeypatch.setattr(sched_mod.time, "sleep", fake_sleep, raising=True)

    try:
        sched_mod.run_scheduler(str(p))
    except SystemExit:
        pass

    assert len(dummy.jobs) == len(cfg.items)

    # simulate execution of 1st job callable
    dummy.jobs[0]["func"]()
    assert len(calls) == 1
    assert calls[0]["flow_yaml"].endswith(".yaml")
