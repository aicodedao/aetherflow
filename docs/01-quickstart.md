# 01 — Quickstart

Goal: in a few minutes you should be able to:

install → run a flow → run with a bundle → run with the scheduler

All CLI commands below are implemented in:
- `aetherflow.core.cli`
- `aetherflow.scheduler.cli`

Public API surface (for code integrations):
- `aetherflow.core.api`

---

# 1) Install

You can install from PyPI or from this repository.

---

## From PyPI

### Core only

```bash
pip install aetherflow-core
````

### Scheduler only

```bash
pip install aetherflow-scheduler
```

### Meta package (recommended for users)

Installs both core + scheduler:

```bash
pip install aetherflow
```

---

## Extras (optional dependencies)

Extras are defined in `aetherflow-core`’s `pyproject.toml`.

Common extras:

* `aetherflow-core[all]` — install all optional dependencies
* `aetherflow-core[reports]` — reporting bundle (DuckDB + Parquet + Excel)
* `aetherflow-core[duckdb]` — DuckDB connector
* `aetherflow-core[parquet]` — Parquet support
* `aetherflow-core[excel]` — Excel template filling

Example:

```bash
pip install "aetherflow-core[all]"
```

Exact extras depend on the package version you installed.

---

## From repository (editable mode)

Recommended for development.

From repo root:

```bash
pip install -e packages/aetherflow-core
pip install -e packages/aetherflow-scheduler
pip install -e packages/aetherflow
```

If you want dev + optional extras:

```bash
pip install -e "packages/aetherflow-core[all,dev]"
pip install -e "packages/aetherflow-scheduler[dev]"
```

---

# 2) Run Your First Flow

Create `flow.yaml`:

```yaml
version: 1

flow:
  id: hello
  workspace:
    root: /tmp/work
    cleanup_policy: never
  state:
    backend: sqlite
    path: /tmp/state/hello.sqlite

jobs:
  - id: hello
    steps:
      - id: echo
        type: external.process
        inputs:
          command: ["bash", "-lc", "echo hello from aetherflow"]
          timeout_seconds: 30
```

What this flow does:

* Defines a workspace under `/tmp/work`
* Uses SQLite state at `/tmp/state/hello.sqlite`
* Runs a single OS-level command

---

## Validate first (recommended)

```bash
aetherflow validate flow.yaml
```

Validation checks:

* YAML schema (FlowSpec)
* semantic rules (job ordering, depends_on, when expressions)
* template resolution contract

JSON output:

```bash
aetherflow validate flow.yaml --json
```

---

## Run it

```bash
aetherflow run flow.yaml
```

Core execution sequence:

1. Parse + validate spec
2. Snapshot environment
3. Initialize state backend
4. Execute jobs sequentially
5. Persist step/job status
6. Emit run summary

Artifacts will appear under:

```bash
/tmp/work/
```

State DB:

```bash
/tmp/state/hello.sqlite
```

---

# 3) Run With a Bundle Manifest

Bundles provide:

* synced flows
* synced profiles
* synced plugins
* synced env files
* fingerprinted, reproducible local activation

## Sync bundle

```bash
aetherflow bundle sync --bundle-manifest ./manifest.yaml
```

## Check bundle status

```bash
aetherflow bundle status --bundle-manifest ./manifest.yaml
```

## Run flow with bundle

```bash
aetherflow run flow.yaml --bundle-manifest ./manifest.yaml
```

When `--bundle-manifest` is provided:

1. Bundle is synced
2. Local cached root is activated
3. Profiles/plugins/env files are loaded from bundle layout
4. Flow executes deterministically

Optional safety flag:

```bash
aetherflow run flow.yaml \
  --bundle-manifest ./manifest.yaml \
  --allow-stale-bundle
```

See:
→ 08-manifest-and-bundles.md

---

# 4) Run With the Scheduler

The scheduler package wraps APScheduler and delegates execution to core.

Create `scheduler.yaml`:

```yaml
timezone: Europe/Berlin

items:
  - id: nightly-hello
    cron: "0 2 * * *"
    flow_yaml: flow.yaml
    # optional:
    # bundle_manifest: bundle.yaml
    # allow_stale_bundle: false
    # flow: hello
    # job: hello
    # misfire_grace_time: 300
```

Run:

```bash
aetherflow-scheduler run scheduler.yaml
```

Scheduler behavior:

* loads scheduler YAML
* registers cron jobs
* triggers `aetherflow run`
* does not embed runner logic
* uses core state for resume

Stop with `Ctrl+C`.

See:
→ 07-scheduler-yaml-guide.md

---

# 5) Quick Resume Demo (Optional)

Force a failure (edit SQL to invalid query).

Run:

```bash
aetherflow run flow.yaml --run-id demo1
```

Fix it.

Resume:

```bash
aetherflow run flow.yaml --run-id demo1
```

Previously successful steps will be skipped.

That’s state-backed resume in action.

---

# 6) What You Just Covered

You have:

* Installed the engine
* Validated a flow
* Executed it locally
* Used bundles for reproducible execution
* Scheduled it with cron-style config
* Observed state + resume semantics

That’s the full minimal lifecycle.

---

# 7) Next Steps

Go deeper:

* 93-flow-in-15-minutes.md — fastest build path
* 10-flow-yaml-guide.md — jobs, gating, locks, retries
* 09-profiles-and-resources.md — env snapshot + profiles
* 23-builtins-catalog.md — connectors + steps
* 24-responsibility-model.md — enterprise vs internal_fast
