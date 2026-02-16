from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field, RootModel
from pydantic.config import ConfigDict


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


class SchedulerItemSpec(BaseModel):
    """scheduler.yaml schema.

    Exactly one of 'manifest' or 'flow_yaml' must be provided.
    """
    model_config = ConfigDict(extra="forbid")

    id: str
    cron: str
    flow_yaml: str
    flow: Optional[str] = None  # alias (optional)
    flow_job: Optional[str] = None
    bundle_manifest: Optional[str] = None
    allow_stale_bundle: bool = False
    misfire_grace_time: int = 300

    def model_post_init(self, __context: Any) -> None:
        # normalize alias
        if not self.flow_yaml and self.flow:
            self.flow_yaml = self.flow
        have_manifest = bool(self.bundle_manifest)
        have_flow = bool(self.flow_yaml)
        if have_manifest == have_flow:
            raise ValueError("scheduler.yaml must set exactly one of 'manifest' or 'flow_yaml'")


class SchedulerFileSpec(BaseModel):
    """scheduler.yaml schema (multi-item)."""
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    timezone: str = "Europe/Berlin"
    items: List[SchedulerItemSpec] = Field(default_factory=list)


__all__ = [
    # scheduler
    "SchedulerFileSpec",
    "SchedulerItemSpec",
]