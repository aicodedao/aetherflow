from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Optional


class StateStore:
    def __init__(self, db_path: str):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=30, isolation_level=None)

    def _init(self):
        with self._connect() as c:
            c.execute("PRAGMA journal_mode=WAL;")
            c.execute(
                """CREATE TABLE IF NOT EXISTS job_runs(
                    job_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(job_id, run_id)
                );"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS step_runs(
                    job_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    updated_at INTEGER NOT NULL,
                    PRIMARY KEY(job_id, run_id, step_id)
                );"""
            )
            c.execute(
                """CREATE TABLE IF NOT EXISTS locks(
                    key TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    expires_at INTEGER NOT NULL
                );"""
            )

    def set_job_status(self, job_id: str, run_id: str, status: str):
        now = int(time.time())
        with self._connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO job_runs(job_id, run_id, status, updated_at) VALUES (?,?,?,?)",
                (job_id, run_id, status, now),
            )

    def set_step_status(self, job_id: str, run_id: str, step_id: str, status: str):
        now = int(time.time())
        with self._connect() as c:
            c.execute(
                "INSERT OR REPLACE INTO step_runs(job_id, run_id, step_id, status, updated_at) VALUES (?,?,?,?,?)",
                (job_id, run_id, step_id, status, now),
            )

    def get_step_status(self, job_id: str, run_id: str, step_id: str) -> Optional[str]:
        with self._connect() as c:
            row = c.execute(
                "SELECT status FROM step_runs WHERE job_id=? AND run_id=? AND step_id=?",
                (job_id, run_id, step_id),
            ).fetchone()
            return row[0] if row else None

    def acquire_lock(self, key: str, owner: str, ttl_seconds: int = 600) -> bool:
        now = int(time.time())
        exp = now + int(ttl_seconds)
        with self._connect() as c:
            c.execute("DELETE FROM locks WHERE expires_at <= ?", (now,))
            try:
                c.execute("INSERT INTO locks(key, owner, expires_at) VALUES (?,?,?)", (key, owner, exp))
                return True
            except sqlite3.IntegrityError:
                return False

    def release_lock(self, key: str, owner: str) -> None:
        with self._connect() as c:
            c.execute("DELETE FROM locks WHERE key=? AND owner=?", (key, owner))
