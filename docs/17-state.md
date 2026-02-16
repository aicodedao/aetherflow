# 17 — State (Backend & Persistence)

Source of truth:

- `aetherflow.core.state.StateStore`

At the time of writing, the only backend implemented in core is:

- **SQLite** (single file database)

There is no alternative backend (e.g., Postgres, Redis) in `aetherflow-core`.

State underpins:

- Resume semantics
- Job/step status tracking
- Distributed locking
- Crash recovery

If this document and `StateStore` disagree, the code is authoritative.

---

## 1) Backend Overview

State is persisted in a SQLite database file.

The path is defined by:

flow:
state:
backend: sqlite
path: "/tmp/state/state.db"

Each flow run writes to the same state DB (unless configured otherwise in the flow spec).

SQLite is used in:

- WAL mode
- Autocommit mode

This provides atomic updates with minimal operational overhead.

---

## 2) Database Schema

`StateStore` creates and manages three core tables.

### 2.1 job_runs

Composite primary key:

- job_id
- run_id

Columns:

- job_id (TEXT)
- run_id (TEXT)
- status (TEXT)
- updated_at (INTEGER, epoch seconds)

Purpose:

- Track job-level status for each run
- Support resume and reporting
- Enable dependency evaluation (`depends_on`)

---

### 2.2 step_runs

Composite primary key:

- job_id
- run_id
- step_id

Columns:

- job_id (TEXT)
- run_id (TEXT)
- step_id (TEXT)
- status (TEXT)
- updated_at (INTEGER)

Purpose:

- Track per-step status
- Enable resume semantics
- Prevent re-running completed steps

---

### 2.3 locks

Primary key:

- key

Columns:

- key (TEXT)
- owner (TEXT)
- expires_at (INTEGER, epoch seconds)

Purpose:

- Implement distributed mutex locks
- Prevent overlapping critical sections across runs/processes

See:
- `05-locking-guide.md`

---

## 3) Atomic Writes & Crash Recovery

SQLite configuration:

- `journal_mode = WAL`
- `isolation_level = None` (autocommit)

Implications:

- Each status update is atomic
- Committed rows survive process crash
- No partial writes for single UPDATE/INSERT operations

If a crash happens:

- Steps already marked SUCCESS/SKIPPED remain persisted
- Uncommitted operations are not visible
- Runner can safely resume from state

This design avoids:

- In-memory state reliance
- Log replay complexity
- External transaction coordination

---

## 4) Resume Semantics

Resume logic is state-driven.

Before executing a step, the runner calls:

get_step_status(job_id, run_id, step_id)

If status is:

- SUCCESS
- SKIPPED

The runner does not re-run the step.

This enables:

- Safe retry after crash
- Idempotent re-invocation of the flow
- Deterministic continuation

Important:

Resume relies on:
- Correct state writes
- Idempotent step design

State does not magically fix non-idempotent side effects.

See:
- `03-execution-model.md`
- `20-steps.md`

---

## 5) Job Status and Dependency Evaluation

For each job, the runner:

- checks dependency jobs via job_runs table
- evaluates status before execution

If dependency status ≠ SUCCESS:

- job becomes BLOCKED
- steps are not executed

Job-level status transitions are persisted in `job_runs`.

---

## 6) Locking via State

The `locks` table implements distributed mutex behavior.

Lock lifecycle:

- Acquire:
    - insert/update lock row if expired or allowed
- Use:
    - critical section executes
- Release:
    - delete lock row if owner matches

TTL enforcement:

- `expires_at` defines lock expiry
- expired locks can be re-acquired

Because locks live in SQLite:

- they work across processes
- they work across scheduler-triggered runs
- they survive process restarts (until TTL expiry)

See:
- `05-locking-guide.md`

---

## 7) Retention & Cleanup

Core retention behavior:

- Only workspace directories are cleaned based on `cleanup_policy`
- State database rows are **not automatically pruned**

There is no built-in retention policy for:

- old job_runs
- old step_runs
- old locks (expired locks are reused, not purged automatically)

If retention is required, you must:

- rotate state DB file
- delete old rows manually
- archive state externally

This is a deliberate design choice:
- core avoids implicit data deletion
- operational retention policy is environment-specific

---

## 8) Operational Best Practices

1) Store state DB on durable storage
    - not on ephemeral container FS if resume matters

2) Avoid sharing one state DB across unrelated flows
    - use separate DB paths per flow if isolation is required

3) Monitor DB growth
    - especially in high-frequency schedules

4) Use locking intentionally
    - do not rely on scheduler `max_instances=1` alone

---

## 9) Summary

StateStore provides:

- Durable job and step status tracking
- Resume semantics
- Distributed locking
- Crash-safe persistence

Design principles:

- Simple (SQLite only)
- Deterministic
- Atomic
- Explicit (no hidden retention or cleanup)

State is the backbone of resume and locking.
Treat it as infrastructure, not as a cache.
