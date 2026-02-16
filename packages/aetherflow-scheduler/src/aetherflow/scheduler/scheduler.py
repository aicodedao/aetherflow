from __future__ import annotations

import logging
import time
import yaml

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from aetherflow.core.runner import run_flow
from aetherflow.scheduler.spec import SchedulerFileSpec

log = logging.getLogger("aetherflow.scheduler")


def run_scheduler(scheduler_yaml: str) -> None:
    logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    with open(scheduler_yaml, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    cfg = SchedulerFileSpec.model_validate(raw)
    tz = cfg.timezone
    sched = BackgroundScheduler(timezone=tz)

    for i, it in enumerate(cfg.items):
        sched.add_job(
            func=lambda it=it: run_flow(
                it.flow_yaml,
                flow_job=it.flow_job,
                bundle_manifest=it.bundle_manifest,
                allow_stale_bundle=bool(it.allow_stale_bundle),
            ),
            trigger=CronTrigger.from_crontab(it.cron, timezone=tz),
            id=it.id,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=int(it.misfire_grace_time),
        )
        log.info(f"Scheduled {it.id} -> {it.cron}")

    sched.start()
    log.info("Scheduler running ...")
    try:
        while True:
            time.sleep(1)
    finally:
        sched.shutdown(wait=False)
