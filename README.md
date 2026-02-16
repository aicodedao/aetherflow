# AetherFlow

**AetherFlow** is a YAML-first workflow engine for ops-grade ETL/ELT/Automation workloads.

It is designed to run safely and deterministically on:

- cron
- containers
- lightweight schedulers
- CI/CD jobs
- simple VM environments

No UI.  
No webserver.  
No hidden magic.

If you want a boring, reproducible, blame-proof runner — this is it.

---

# Why AetherFlow?

AetherFlow focuses on:

- ✅ **Deterministic execution** — same inputs → same state transitions  
- ✅ **State-backed resume** — safe reruns using `run_id`  
- ✅ **Strict templating** — no Jinja, no implicit magic  
- ✅ **Explicit locking** — prevent overlapping runs  
- ✅ **Bundle-based reproducibility** — fingerprinted flow + profiles + plugins  
- ✅ **YAML-first design** — spec is data, easy to review and audit  

It does not try to be a platform.

---

# What AetherFlow Is Not

AetherFlow is NOT:

- Apache Airflow
- A UI-first orchestrator
- A webserver
- A compute engine
- A cluster manager

It does not provision compute.  
It runs on top of the compute you already have.

---

# Install

## Meta package (recommended)

```bash
pip install aetherflow
````

This installs:

* `aetherflow-core`
* `aetherflow-scheduler`

---

## Core only

```bash
pip install aetherflow-core
```

Optional extras:

```bash
pip install "aetherflow-core[all]"
pip install "aetherflow-core[reports]"
pip install "aetherflow-core[duckdb]"
pip install "aetherflow-core[excel]"
```

---

## Scheduler only

```bash
pip install aetherflow-scheduler
```

---

# Quick Example

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
  - id: main
    steps:
      - id: echo
        type: external.process
        inputs:
          command: ["bash", "-lc", "echo hello from aetherflow"]
          timeout_seconds: 30
```

Validate:

```bash
aetherflow validate flow.yaml
```

Run:

```bash
aetherflow run flow.yaml
```

Artifacts appear under `/tmp/work/`
State is stored in `/tmp/state/hello.sqlite`

---

# Scheduler Example

Create `scheduler.yaml`:

```yaml
timezone: Europe/Berlin

items:
  - id: nightly
    cron: "0 2 * * *"
    flow_yaml: flow.yaml
```

Run:

```bash
aetherflow-scheduler run scheduler.yaml
```

---

# Execution Model

AetherFlow runs:

```
Flow → Job → Step
```

Core behavior:

* Jobs execute sequentially
* Steps execute sequentially within a job
* Resume skips steps already marked `SUCCESS` or `SKIPPED`
* Locking is explicit via `with_lock`
* Template resolution is strict and minimal

---

# Built-In Capabilities

Core includes built-ins for:

* Databases (SQLAlchemy, SQLite, DuckDB, Postgres, MySQL, Oracle, Exasol)
* REST (httpx)
* SMTP mail
* SFTP (paramiko)
* SMB
* Zip/Unzip
* Excel reporting
* External OS process execution
* Locking
* State + resume

See the documentation for the full built-ins catalog.

---

# Philosophy

* **YAML-first**
* **Config over code**
* **Strict templating contract**
* **Single resolver architecture**
* **Explicit decisions, not hidden defaults**
* **Boring deterministic runner**

AetherFlow prefers clarity over convenience.

---

# Public API

Stable public API surface:

```python
from aetherflow.core.api import ...
```

Everything else is internal and may change in minor releases.

---

# Docs

Canonical documentation ships with the project.

Recommended reading order:

1. Overview
2. Architecture
3. Quickstart
4. Flow YAML Guide
5. Builtins Catalog
6. Failure Recovery Playbook

---

# License

ref. [LICENSE](LICENSE)

---

# Final Note

If you want a deterministic, YAML-first engine that runs cleanly in cron/containers and is easy to debug — use AetherFlow.
