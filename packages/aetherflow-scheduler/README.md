# aetherflow-scheduler

`aetherflow-scheduler` is a **thin cron-style scheduler** for AetherFlow, built on **APScheduler**.

It reads a YAML file and triggers `aetherflow` runs on a schedule. The design goal is simplicity:
- Core stays **run-once** and deterministic
- Scheduler is the **run-on-cron** wrapper

This distribution ships the CLI **`aetherflow-scheduler`**.

---

## Install

```bash
pip install aetherflow-scheduler
```

This depends on `aetherflow-core` and installs it automatically.

Python: **3.11+**.

---

## CLI

```bash
aetherflow-scheduler --help
aetherflow-scheduler run path/to/scheduler.yaml
```

---

## Scheduler YAML (schema)

Top-level keys:
- `timezone` *(string, optional)*: timezone name (IANA tz database). Default: `"Europe/Berlin"`.
- `items` *(list, required)*: list of scheduled items

Each item:
- `id` *(string, required)*: APScheduler job id
- `cron` *(string, required)*: crontab expression (e.g. `"0 * * * *"`)
- `flow_yaml` *(string, required)*: path to a flow YAML file
- `flow` *(string, optional)*: flow id inside the YAML
- `flow_job` *(string, optional)*: job id within the flow
- `bundle_manifest` *(string, optional)*: bundle manifest path (sync before run)
- `allow_stale_bundle` *(bool, optional)*: default `false`
- `misfire_grace_time` *(int seconds, optional)*: default `300`

Example:

```yaml
timezone: Europe/Berlin
items:
  - id: hourly_sales
    cron: "0 * * * *"
    flow_yaml: "flows/sales.yaml"
    flow: "sales_flow"
    flow_job: "main"
    bundle_manifest: "bundles/sales_bundle.yaml"
    allow_stale_bundle: true
    misfire_grace_time: 600
```

Run it:

```bash
aetherflow-scheduler run scheduler.yaml
```

---

## Overlap prevention and reliability

AetherFlow itself can use **locks/state** to avoid overlapping executions and to support recovery patterns.
Scheduler is intentionally minimal: it triggers runs; the “safety” lives in core.

Relevant docs:
- `aetherflow/docs/05-locking-guide.md`
- `aetherflow/docs/17-state.md`
- `aetherflow/docs/15-concurrency.md`
- `aetherflow/docs/404-Failure-Recovery-Playbook.md`

---

## Namespace package rule (important)

AetherFlow is a **PEP 420 implicit namespace** across distributions.

Use:
- `import aetherflow.scheduler`
- `import aetherflow.core`
- `from aetherflow.core.api import ...`

Do **not** rely on ambiguous imports like `aetherflow.x`.

---

## Docs (in this repository)

Scheduler-specific doc:
- `aetherflow/docs/07-scheduler-yaml-guide.md`

Start here:
- `aetherflow/docs/README.md`
- `aetherflow/docs/INDEX.md`
