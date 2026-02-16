# 03 — Execution Model

Relevant modules:

- `aetherflow.core.runner`
- `aetherflow.core.state`
- `aetherflow.core.steps.base`

This document explains how AetherFlow executes a flow end-to-end, how state is persisted, how resume works, and how status transitions are modeled.

The design goal is simple: deterministic, sequential, and resume-safe execution.

---

# 1. High-Level Execution Flow

A single `aetherflow run flow.yaml` execution follows this lifecycle:

1. Build immutable environment snapshot
2. Load settings from snapshot
3. Load plugins (if configured)
4. Parse and validate `FlowSpec`
5. Resolve resources and build connectors
6. Execute jobs sequentially
7. Persist state and apply cleanup policy

Each execution is identified by a unique:

```
run_id
```

Every run operates against an immutable environment snapshot.

---

# 2. Environment & Settings

## Environment Snapshot

At startup, the runner creates a snapshot from:

- `os.environ`
- Optional env files
- Optional bundle manifest context

The runner does **not mutate `os.environ`**.

All resolution and settings derive from this snapshot.

This guarantees:

- Reproducibility
- Isolation between runs
- Deterministic configuration

---

## Settings Loading

Settings are derived from the snapshot and may include:

- Workspace root
- State backend configuration
- Log level
- Strict templating mode
- Plugin paths

Settings are immutable for the duration of a run.

---

# 3. Spec Parsing & Validation

The YAML file is parsed into a Pydantic model:

```python
FlowSpec.model_validate(...)
```

Validation includes:

- Structural schema validation
- Semantic validation rules
- Resolution checks (depending on strict mode)

Modules:

- Spec definitions: `aetherflow.core.specs`
- Validation rules: `aetherflow.core.validation`

If validation fails, execution stops before any job runs.

---

# 4. Resources and Connectors

After validation:

1. Resource definitions are resolved
2. Secrets are decoded / expanded (if configured)
3. Connectors are instantiated

Connectors are accessible via execution context:

```python
ctx.connectors["resource_name"]
```

Connectors:

- Wrap external drivers (DB, HTTP, SFTP, etc.)
- Are built from resolved resource config
- Should not use global state

---

# 5. Flow Execution Boundary

Execution structure:

```
Flow
  ├── Job
  │     ├── Step
  │     ├── Step
  │     └── Step
  └── Job
```

Important constraints:

- Jobs execute sequentially
- Steps execute sequentially within a job
- The core runner does not introduce parallelism
- Concurrency must be external (scheduler, containers, multiple processes)

Steps may use internal concurrency if appropriate, but that is an implementation detail.

---

# 6. Job Execution Model

For each job, the runner:

## 6.1 Evaluate Dependencies

If `depends_on` references a job that did not finish with `SUCCESS`:

```
Job → BLOCKED
```

The job does not execute.

---

## 6.2 Evaluate `when` Condition

If the job-level `when` expression evaluates to false:

```
Job → SKIPPED
```

No steps execute.

---

## 6.3 Execute Steps Sequentially

Steps execute in declared order.

No implicit retries or parallelism occur at runner level.

---

## 6.4 Artifact Directory

Each job has a dedicated directory:

```
<work_root>/<flow_id>/<job_id>/<run_id>/
```

This directory stores:

- Artifacts
- Scratch files
- Step outputs
- Logs (if configured)

---

## 6.5 Locking (Explicit)

Locking is explicit.

Distributed locks are stored in the state backend.

The built-in `with_lock` step can protect critical sections.

Lock behavior is documented in:

→ `05-locking-guide.md`

---

# 7. Step Execution Model

Steps are executed sequentially.

A step must:

- Be idempotent or resume-friendly
- Write outputs atomically
- Avoid mutating process-wide state
- Declare skip behavior explicitly

Steps return:

```python
StepResult(status, outputs)
```

Where status is:

- `SUCCESS`
- `SKIPPED`

---

## 7.1 Resume Behavior

Before running a step, the runner checks state.

If state already records:

- `SUCCESS`
- `SKIPPED`

The step is not executed again.

This enables crash recovery and safe resume.

---

## 7.2 Short-Circuiting

If a step returns `SKIPPED` and is configured with:

```yaml
on_no_data: skip_job
```

Then:

- Remaining steps in the job are not executed
- Job status becomes `SKIPPED`

This allows “no new data” to be treated as a valid outcome.

---

# 8. Status Model

AetherFlow treats `SKIPPED` as a first-class state.

It is not a failure.

This supports:

- Conditional execution
- No-data scenarios
- Deterministic short-circuit behavior

---

## 8.1 Job Status

Possible job states:

- `SUCCESS`
- `FAILED`
- `BLOCKED`
- `SKIPPED`

### Definitions

- `SUCCESS` → All steps completed successfully
- `FAILED` → At least one step failed
- `BLOCKED` → Dependency did not succeed
- `SKIPPED` → Condition false or short-circuited

---

## 8.2 Step Status

Possible step states:

- `SUCCESS`
- `SKIPPED`

Failure results in job failure unless explicitly handled by step logic.

---

# 9. State Backend

Default backend:

```
SQLite (StateStore)
```

Module:

- `aetherflow.core.state`

The state store records:

- run_id
- job_id
- step_id
- status transitions
- lock ownership

State enables:

- Resume
- Locking
- Crash recovery

Atomic writes and durable persistence are required for correctness.

See:

→ `17-State.md`

---

# 10. Cleanup Policy

Workspace cleanup is controlled by:

```
cleanup_policy: on_success | always | never
```

Behavior:

- `on_success` → delete job directory after success
- `always` → delete regardless of outcome
- `never` → preserve artifacts

Cleanup affects workspace only.

State history remains intact.

---

# 11. Design Guarantees

The execution model guarantees:

- Sequential job execution
- Sequential step execution
- Deterministic state transitions
- Immutable environment snapshot
- Explicit locking
- Resume-safe behavior

It intentionally avoids:

- Implicit parallelism
- Hidden retries
- Global environment mutation
- Implicit orchestration logic

The result is a predictable runner suitable for cron, containers, and production ETL workloads.
