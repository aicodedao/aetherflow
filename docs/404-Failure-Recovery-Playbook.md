# 404 — Failure Recovery Playbook (Core-accurate)

Required links:
- State: [17-state](17-state.md)
- Observability: [16-observability](16-observability.md)

Source reviewed:
- Runner + resume/state writes: `aetherflow.core.runner`
- State DB schema + locks: `aetherflow.core.state`
- Event logging + metrics hook: `aetherflow.core.observability`
- Templating failures: `aetherflow.core.resolution`
- Lock primitive: builtin step `with_lock` + `ctx.state.acquire_lock(...)`

This playbook answers:
- what happens for common failure modes
- where to look (state, logs, artifacts)
- how to debug fast
- how to resume safely without duplicating side effects

---

# 0) Where to look first (always)

## A) Logs (primary truth)
AetherFlow logs to standard logging (stdout/stderr by default).  
Two formats exist (Settings: `AETHERFLOW_LOG_FORMAT`):
- `text` (default)
- `json` (one JSON object per line)

Core emits lifecycle events via `RunObserver`:
- `run_start`
- `job_start` / `job_end`
- `step_start` / `step_end`
- `run_summary`

If you have JSON logs, grep by:
- `flow_id`
- `run_id`
- `job_id`
- `step_id`

## B) State DB (resume truth)
State is SQLite (core implementation) and contains only:
- `job_runs(job_id, run_id, status, updated_at)`
- `step_runs(job_id, run_id, step_id, status, updated_at)`
- `locks(key, owner, expires_at)`

This is what drives resume:
- if `step_runs.status` is `SUCCESS` or `SKIPPED`, runner will **skip** that step on rerun with the same `run_id`
- if missing (no row), the step will run again

## C) Artifacts (what actually got produced)
Job workspace layout (from `RunContext`):

```

<work_root>/<flow_id>/<job_id>/<run_id>/
<layout.artifacts>/
<layout.scratch>/
<layout.manifests>/

````

If you are in triage mode:
- set `cleanup_policy: never` so the job dir stays around after success/failure

---

# 1) Step crash (Python exception inside a step)

## What happens (core behavior)
- runner sets job status to `RUNNING` at job start
- it calls `step.run()`
- if the step raises:
  - the job is marked `FAILED` in `job_runs`
  - the exception is logged with stacktrace (`job_log.exception(...)`)
  - **step status may not be written** (because `set_step_status` happens only after step returns)

In logs you will see:
- `step_start` for that step
- **no** `step_end` for that step
- `Job failed: ...` with stacktrace

In state:
- `job_runs.status = FAILED`
- `step_runs` for failed step may be absent (common)

## Debug checklist
- find the first stacktrace in logs for that run_id
- inspect job artifacts dir for partial outputs
- check whether the step had side effects (uploads, external writes)

## Safe recovery / resume
- fix the code or external dependency
- rerun with the **same** `--run-id` if you want resume semantics:
  - steps already `SUCCESS/SKIPPED` will be skipped
  - the crashed step (no status) will run again

Command pattern:

```bash
aetherflow run flow.yaml --run-id <same_run_id>
````

If the step is **not idempotent**, do NOT resume blindly:

* add a marker strategy (file marker / atomic dir)
* or wrap it behind `with_lock` + explicit idempotency checks

---

# 2) Process killed (SIGKILL / container killed / VM terminated)

This includes:

* orchestrator kills container
* node reboot
* OOM kill
* `kill -9` on the runner process

## What happens (core behavior)

The runner may die at any point:

* before updating state
* mid-step
* mid-job

Common state outcomes:

* job may be stuck as `RUNNING` (runner wrote it before starting steps)
* steps that completed before the kill likely have `SUCCESS/SKIPPED`
* the currently running step likely has **no step_runs row** (unless it had already finished)

Locks:

* locks are stored in SQLite with TTL (`expires_at`)
* if the process dies, locks are NOT auto-released
* they clear when TTL expires or when you delete the lock row

## Debug checklist

* identify last emitted log event:

    * if last event is `step_start`, the kill happened mid-step
    * if last event is `run_start` with nothing else, it died early
* inspect artifacts for partial files
* inspect locks table (if you use `with_lock`)

## Safe recovery / resume

* if you want to resume the same run:

    * rerun with the same `--run-id`
    * steps already recorded as `SUCCESS/SKIPPED` will be skipped
    * the in-flight step will rerun

If you suspect side effects happened but state didn’t record success:

* do NOT trust resume blindly
* inspect the target system (SFTP/SMB/db table/object storage)
* add idempotency markers and re-run once safe

---

# 3) `external.process` timeout / kill

## What happens (builtin behavior)

`external.process` enforces `timeout_seconds`:

* on timeout: sends terminate, waits `kill_grace_seconds`, then kills
* it raises an error (job becomes `FAILED`) unless you configured retry behavior

In logs you will see:

* the command invocation
* non-zero exit code or timeout exception
* `job_end` status `FAILED`

In state:

* the step will usually have no `SUCCESS` record (it failed)
* previous steps can still be `SUCCESS`

## Debug checklist

* check stdout/stderr mode:

    * if `log.stdout=inherit`, output is in runner logs
    * if `capture`, output is in step output (and logs still show lifecycle)
    * if `file`, inspect the log file path from step outputs (if returned)
* reproduce locally with the same `cwd` and env

## Safe recovery / resume

* fix the underlying cause (tool config, env vars, resource availability)
* rerun with same `--run-id` to resume

Ops best practice:

* for non-idempotent tools, add:

    * marker file checks
    * atomic output dir strategy
    * `with_lock` around the process if overlap is dangerous

---

# 4) Lock not acquired / lock timeout (via `with_lock`)

Core lock implementation:

* `with_lock` calls `ctx.acquire_lock(lock_key, ttl_seconds)`
* state store stores lock row: `(key, owner=run_id, expires_at=now+ttl)`
* if lock exists and not expired → acquire returns false → `with_lock` raises `RuntimeError("Lock not acquired: ...")`

## Symptoms

* job fails quickly
* logs show `Lock not acquired: <key>`
* state has a lock row that blocks new runs until TTL expires

## Debug checklist

Inspect locks:

```sql
SELECT key, owner, expires_at FROM locks;
```

Interpretation:

* `expires_at` is epoch seconds
* if `expires_at` is in the past, the next acquire will delete expired locks and succeed

## Safe recovery

Option A (recommended): wait TTL

* safest because you avoid overlapping runs

Option B (manual unlock): delete lock row
Only do this if you are sure the previous run is dead and no side effects are still in-flight:

```sql
DELETE FROM locks WHERE key = '<lock_key>';
```

After lock is cleared:

* rerun with same run_id to resume (or new run_id if you want a fresh run)

---

# 5) Invalid spec (schema/semantic validation)

There are two layers:

## A) Schema (FlowSpec parsing)

If YAML doesn’t match the Pydantic model:

* `FlowSpec.model_validate(...)` raises `ValidationError`
* runner rethrows as `SpecError`

## B) Semantic constraints (runner checks)

Runner validates:

* unknown `depends_on`
* job dependency ordering (deps must appear earlier)
* invalid `job.when` expression (unsupported AST nodes/names)

## Symptoms

* `aetherflow validate` fails (best way to catch this)
* `aetherflow run` fails before doing real work
* state may have **no entries** if failure occurs before job loop

## What to do

* run:

```bash
aetherflow validate flow.yaml --json
```

* fix the YAML based on the error report
* re-validate until clean
* then run

---

# 6) Missing env / profile mapping issues

There are two common failures:

## A) Missing env referenced by templates (resource resolution)

Resources allow only `{{env.*}}`.
If `{{env.SOMETHING}}` is missing and no default is given:

* `ResolverMissingKeyError`
* occurs during `_build_resources(...)` before jobs execute

Symptoms:

* run fails very early (often after `run_start`)
* no job statuses may be written
* error mentions missing key path

## B) Doctor/validate env warnings vs strict env validation

Core CLI provides:

* `aetherflow doctor flow.yaml` to explain what env keys are required by profiles/resources

Procedure:

1. run doctor:

```bash
aetherflow doctor flow.yaml
```

2. set env vars or fix profile mapping
3. rerun validate/run

Best practice:

* always use defaults for optional env vars:

    * `{{env.MAYBE:}}`
* keep “required env” truly required (no defaults) so it fails loud

---

# 7) Template resolution failure

Templating is intentionally strict (see [99-strict-templating](99-strict-templating.md)).

Two real failure classes:

* `ResolverSyntaxError`

    * invalid syntax (anything not `{{PATH}}` or `{{PATH:DEFAULT}}`)
    * forbidden tokens: `"$" + "{" + "}"`, `"{" + "%" + "%" + "}"`, `"{" + "#" + "#" + "}"`, bare `"{" + "}"` patterns
* `ResolverMissingKeyError`

    * missing key without default (strict behavior)

Where it happens:

* step inputs are rendered before `step_start` is emitted

    * so you may see job start but no step_start for the failing step
* resource config/options are rendered before jobs run

    * so you might only see `run_start` then failure

Debug checklist:

* search for `{{` in YAML
* confirm every token is:

    * `{{env.X}}`, `{{steps.y.z}}`, `{{job.outputs.k}}`, `{{run_id}}`, `{{flow_id}}`
* add defaults where the key may be absent:

    * `{{env.MAYBE:}}`

Safe recovery:

* fix template
* rerun with same run_id if you want resume semantics (only matters if jobs/steps had already completed)

---

# 8) How to debug fast (triage recipe)

## 1) Identify the run

* find `flow_id` + `run_id` from logs
* if you didn’t set `--run-id`, core generates one (12-hex string)

## 2) Read the logs in order

Look for the last lifecycle event:

* last event = `step_start` → died mid-step
* last event = `job_start` → failed before first step (template render, step instantiation)
* only `run_start` → failed during spec/resources/plugins/bootstrap

## 3) Inspect state DB

Check:

* which job is `FAILED`
* which steps are recorded `SUCCESS/SKIPPED`
* whether locks exist

## 4) Inspect artifacts

Look inside:

* `artifacts/` for produced outputs
* `scratch/` for temp or partial files
* `manifests/` for step manifests (if steps write them)

## 5) Decide: resume or restart?

Resume (same run_id) if:

* steps are idempotent OR you can prove they didn’t side-effect twice
* you want to skip already completed work

Restart (new run_id) if:

* you can’t guarantee side-effect safety
* you want a clean run for audit clarity

---

# 9) Safe resume procedure (canonical)

## A) Preserve state + artifacts

* do not delete state DB
* set `cleanup_policy: never` during triage so job dirs remain

## B) Rerun with the same run_id

```bash
aetherflow run flow.yaml --run-id <run_id>
```

Runner resume logic (core):

* skips steps with state status `SUCCESS` or `SKIPPED`
* reruns steps with no status entry (common after crashes/kills/template failures)

## C) After recovery, clean up intentionally

* re-enable `cleanup_policy: on_success` once stable
* consider state retention policy (don’t keep infinite db history in prod)

---

# 10) “If it keeps failing” escalation checklist

* reproduce the failing step in isolation (same inputs/env/cwd)
* downgrade to `log_format=json` for grep-friendly triage
* add marker/idempotency to external side effects
* add `with_lock` for any non-overlap tools
* add a “probe” step + `when` gating so “no data” becomes SKIPPED, not FAILED
