# 15 — Concurrency

AetherFlow’s concurrency model is intentionally simple.

Core execution is deterministic and sequential.
If you need concurrency, you get it by running multiple independent runs (scheduler / multiple processes / containers), not by turning the core runner into a multi-threaded orchestration engine.

Relevant modules:
- `aetherflow.core.runner`
- `aetherflow.scheduler.scheduler` (APScheduler)

---

## 1) Core Runner Concurrency (Deliberately Sequential)

The core runner executes a single flow run in a single process, with a deterministic order:

- Jobs run **sequentially** (in the order defined in YAML, subject to `depends_on` / `when`)
- Steps run **sequentially** within each job

There is no runner-level parallelism:
- no job-level parallel execution
- no step-level parallel execution

Resume semantics are state-driven (SQLite state store), not parallelism-driven.

If the run crashes mid-way, the runner resumes by reading state and skipping steps already marked `SUCCESS` / `SKIPPED`.

See:
- `03-execution-model.md`
- `17-state.md`

---

## 2) Step-Level Internal Concurrency (Allowed, but Local)

A step implementation may internally use:
- threads
- async I/O
- batching

Examples:
- batch uploads
- concurrent API calls
- streaming reads/writes

But this is a step implementation detail and must not change the external contract:

- the step must still be idempotent or resume-friendly
- outputs must be written atomically
- side effects must be explicit

If you rely on internal concurrency, treat it as a local optimization, not a workflow concurrency model.

---

## 3) Scheduler Concurrency (Multiple Runs, Not Parallel Jobs)

The scheduler (`aetherflow-scheduler`) can trigger multiple flow runs based on cron schedules.

APScheduler provides its own execution model (executors/threads/processes depending on configuration). In the current scheduler behavior:

- each scheduled `item` is registered with:
    - `max_instances=1` (prevents overlap for the same item id)
    - `coalesce=True` (missed runs are combined)
    - configurable `misfire_grace_time`

Important:
- `max_instances=1` prevents overlap only for the same scheduler item within that scheduler process.
- it does not prevent:
    - overlap across different items
    - overlap across multiple scheduler processes
    - overlap across manual invocations

If you need cross-run exclusivity, use state-backed locks (`with_lock`).

See:
- `07-scheduler-yaml-guide.md`
- `05-locking-guide.md`

---

## 4) Run Isolation (What Is Isolated vs Shared)

Each run has its own isolated context:

- an immutable env snapshot (`ctx.env`)
- a unique `run_id`
- a unique work directory:
    - `<work_root>/<flow_id>/<job_id>/<run_id>/`

Each run typically shares:

- the same state backend path (from flow spec):
    - `flow.state.path` (SQLite file)
- optionally the same bundle cache root (if bundle is used)

This is intentional:
- shared state enables resume, locking, and crash recovery across runs
- isolation via run_id prevents artifact collisions

---

## 5) Global State Rules (Non-Negotiable)

To keep runs safe and reproducible:

Do not:
- mutate `os.environ` during execution
- store mutable global state in singletons used across runs
- cache connector instances across runs unless you fully understand the risks

Prefer:
- read from `ctx.env`
- build connectors via the connector manager
- keep step logic pure and deterministic
- use state-backed locks for shared side effects

Connector caching exists as a controlled feature (settings-driven). If you enable caching beyond run scope, you accept the blast radius.

See:
- `11-envs.md`
- `14-settings.md`
- `19-connectors.md`

---

## 6) Practical Concurrency Patterns

### Pattern A — Parallelize at the orchestration layer
Run multiple flows in parallel by:
- scheduler triggering different items
- separate containers
- separate processes

Keep each flow run sequential internally.

### Pattern B — Guard shared side effects with locks
If two runs might collide:
- wrap the critical section with `with_lock`
- pick a meaningful lock key
- set TTL based on worst-case runtime

### Pattern C — Split probing from processing
Use one small job to probe and output a gate flag, then:
- downstream jobs run only when needed (`when`)

This reduces unnecessary concurrency pressure and keeps runs efficient.

---

## 7) Summary

- Core runner: sequential jobs, sequential steps, deterministic behavior.
- Scheduler: triggers multiple independent runs; prevents overlap per item via `max_instances=1`.
- True concurrency is achieved by running multiple runs externally (scheduler/process/container).
- Run isolation: per-run env snapshot + artifacts; shared state backend for resume/locking.
- Global state mutation is forbidden if you want reproducibility.

Boring concurrency is the point.
