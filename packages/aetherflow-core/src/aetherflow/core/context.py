from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from aetherflow.core.runtime.settings import Settings
from aetherflow.core.state import StateStore


@dataclass
class RunContext:
    settings: Settings
    flow_id: str
    run_id: str
    work_root: Path
    layout: Dict[str, str]
    state: Optional[StateStore]
    resources: Dict[str, dict]
    env: Dict[str, str] = field(default_factory=dict)
    connectors: Dict[str, Any] = field(default_factory=dict)
    log: logging.Logger = field(default_factory=lambda: logging.getLogger("aetherflow.core.context"))

    def job_dir(self, job_id: str) -> Path:
        p = self.work_root / self.flow_id / job_id / self.run_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def artifacts_dir(self, job_id: str) -> Path:
        p = self.job_dir(job_id) / self.layout["artifacts"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    def scratch_dir(self, job_id: str) -> Path:
        p = self.job_dir(job_id) / self.layout["scratch"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    def manifests_dir(self, job_id: str) -> Path:
        p = self.job_dir(job_id) / self.layout["manifests"]
        p.mkdir(parents=True, exist_ok=True)
        return p

    def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        return self.state.acquire_lock(key, owner=self.run_id, ttl_seconds=ttl_seconds)

    def release_lock(self, key: str) -> None:
        self.state.release_lock(key, owner=self.run_id)


def new_run_id() -> str:
    return uuid.uuid4().hex[:12]