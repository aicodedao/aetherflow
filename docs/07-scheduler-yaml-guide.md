# 07 — Scheduler YAML Guide

Package: `aetherflow-scheduler`  
Primary module: `aetherflow.scheduler.scheduler` (APScheduler)

AetherFlow separates responsibilities on purpose:

- **Core (`aetherflow-core`)** runs a single flow deterministically (no background threads for flow execution).
- **Scheduler (`aetherflow-scheduler`)** triggers core runs on cron-like schedules.

The scheduler is intentionally lightweight: it is a trigger loop, not an orchestration engine.

---

# 1) Install

```bash
pip install aetherflow-scheduler
```

This installs `aetherflow-core` as a dependency.

---

# 2) Scheduler YAML (Current Schema)

This schema matches the current implementation in `aetherflow.scheduler.scheduler`.

```yaml
timezone: Europe/Berlin   # optional, default: Europe/Berlin

items:
  - id: nightly-hello     # required, unique
    cron: "0 2 * * *"     # required, crontab format
    flow_yaml: flow.yaml  # required, path to Flow YAML
    # optional:
    flow_job: main
    bundle_manifest: bundle.yaml
    allow_stale_bundle: false
    misfire_grace_time: 300
```

---

## Field Reference

### `timezone` (optional)

IANA timezone string.

If omitted, the scheduler defaults to:

- `Europe/Berlin`

---

### `items` (required)

A list of scheduled entries.

Each entry must include:

- `id`
- `cron`
- `flow_yaml`

---

### `items[].id` (required)

Scheduler entry identifier.

Must be unique across items.

This is used as the APScheduler job ID, so duplicates are not allowed.

---

### `items[].cron` (required)

Crontab string.

Example:

- `"0 2 * * *"` (02:00 every day)

Parsed using APScheduler’s `CronTrigger.from_crontab(...)` with the scheduler timezone.

---

### `items[].flow_yaml` (required)

Path to a flow YAML file compatible with `aetherflow-core`.

This file is passed to the core CLI for execution.

---

### `items[].flow_job` (optional)

If provided, only that job is executed from the flow.

This is a convenience for scheduling one job from a larger flow spec.

---

### `items[].bundle_manifest` (optional)

If provided, the scheduler runs core with bundle support.

The scheduler will pass `--bundle-manifest` to `aetherflow run ...`.

---

### `items[].allow_stale_bundle` (optional)

Controls bundle behavior when a remote fetch is not possible or bundle sync is stale.

Default:

- `false`

---

### `items[].misfire_grace_time` (optional)

Seconds to allow a missed run to still execute after its scheduled time.

Default:

- `300`

---

# 3) Runtime Behavior (How Scheduling Works)

At runtime, the scheduler:

- constructs `BackgroundScheduler(timezone=<tz>)`
- registers one APScheduler job per item
- starts the scheduler loop

For each item:

- Trigger:
  - `CronTrigger.from_crontab(cron, timezone=tz)`
- Execution policy:
  - `max_instances=1` (prevent overlap of the same scheduler job ID)
  - `coalesce=True` (combine missed runs into one)
  - `misfire_grace_time` is configurable per item

Important implications:

- `max_instances=1` prevents overlap *within the scheduler* for the same item.
- It does not prevent overlap across different items or across different scheduler processes.
- For cross-process exclusivity, use AetherFlow locking (`with_lock`) backed by state.

See:

→ `05-locking-guide.md`

---

# 4) CLI

Run the scheduler:

```bash
aetherflow-scheduler run scheduler.yaml
```

This starts a background scheduler and registers jobs from the YAML file.

---

# 5) Validation Notes (Current)

At the moment, the scheduler does not perform full Pydantic spec validation of the scheduler YAML before registering jobs.

Practical effect:

- missing keys may fail at runtime when building triggers or registering jobs
- malformed cron strings fail when APScheduler parses them
- duplicate IDs fail when APScheduler job IDs collide

Best practice:

- keep scheduler YAML minimal and explicit
- validate your flow YAML with `aetherflow validate` during CI
- treat scheduler YAML as “deployment config” for your runtime environment

---

# 6) Recommended Production Pattern

Use the scheduler for timing, and use core mechanisms for correctness:

- Use job gating (`depends_on`, `when`) for control flow
- Use step skip (`STEP_SKIPPED`, `on_no_data: skip_job`) for no-data outcomes
- Use `with_lock` for single-writer critical sections

This keeps scheduling simple and keeps correctness inside the deterministic core runner.
