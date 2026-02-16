from pathlib import Path

import yaml
from aetherflow.scheduler.spec import SchedulerFileSpec


def test_demo_scheduler_yaml_validates():
    repo_root = Path(__file__).resolve().parents[3]
    p = repo_root / "demo" / "usecase-singleflow" / "scheduler" / "scheduler.yaml"
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    cfg = SchedulerFileSpec.model_validate(data)

    # top-level
    assert cfg.version == 1
    assert isinstance(cfg.timezone, str) and cfg.timezone

    # items
    assert isinstance(cfg.items, list) and len(cfg.items) > 0, "demo scheduler.yaml must contain at least one item"

    # Validate each schedule item minimal fields
    for i, it in enumerate(cfg.items):
        # it is SchedulerItemSpec (object), not dict
        assert isinstance(it.id, str) and it.id, f"items[{i}].id must be non-empty string"
        assert isinstance(it.cron, str) and it.cron, f"items[{i}].cron must be non-empty string"
        assert isinstance(it.flow_yaml, str) and it.flow_yaml, f"items[{i}].flow_yaml must be non-empty string"

        # optional fields sanity
        assert isinstance(it.misfire_grace_time, int) and it.misfire_grace_time > 0
        assert isinstance(it.allow_stale_bundle, bool)
