# AetherFlow

[![GitHub Repo](https://img.shields.io/badge/GitHub-aetherflow-blue?logo=github)](https://github.com/aicodedao/aetherflow)
[![CI](https://github.com/aicodedao/aetherflow/actions/workflows/ci.yaml/badge.svg)](https://github.com/aicodedao/aetherflow/blob/develop/.github/workflows/ci.yaml)
[![PyPI](https://img.shields.io/pypi/v/aetherflow-core)](https://pypi.org/project/aetherflow-core/)
[![Python](https://img.shields.io/pypi/pyversions/aetherflow-core)](https://pypi.org/project/aetherflow-core/)
[![License](https://img.shields.io/badge/license-Internal-blue)](https://github.com/aicodedao/aetherflow/blob/develop/LICENSE)

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

It does not try to be a platform. It does not provision compute. It runs on top of the compute you already have.
If you want a boring, explainable, ops-grade YAML workflow engine, you’re in the right place.

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

AetherFlow is a **namespace package** (PEP 420).

Correct imports:

```python
import aetherflow.core
import aetherflow.scheduler
````

Stable public API surface (for plugins (connectors/ steps) / integrations):

```python
from aetherflow.core.api import ...
```

Do NOT use: Everything else is internal and may change in minor releases.

```python
from aetherflow import ...
import aetherflow.<something_else>
```

Only these top-level subpackages are valid:

* `aetherflow.core`
* `aetherflow.scheduler`

Everything else is internal unless explicitly exported via:

```
aetherflow.core.api
```

---

# Documentation 

Canonical ships with the project.
- [Github Pages](https://aicodedao.github.io/aetherflow/) 
- [Index in repo](docs/index.md)

## Fast Reading Path

Recommended reading order:

1) Project overview  
   → **[00-overview.md](docs/00-overview.md)**  
   What AetherFlow is (and is not).

2) Architecture decisions  
   → **[02-architecture.md](docs/02-architecture.md)**  
   Single Resolver Architecture, strict templating, config-over-code.

3) Install → run → bundle → scheduler  
   → **[01-quickstart.md](docs/01-quickstart.md)**  
   Get something running immediately.

4) Write real flows safely  
   → **[10-flow-yaml-guide.md](docs/10-flow-yaml-guide.md)**  
   Jobs, steps, gating, locks, retries, resume.

5) 15-minute practical flow  
   → **[93-flow-in-15-minutes.md](93-flow-in-15-minutes.md)**  
   Zero theory. Just run it.

6) Builtins Catalog  
   → **[23-builtins-catalog.md](docs/23-builtins-catalog.md)**  
   Builtin connectors, steps

7) Failure Recovery Playbook  
   → **[404-Failure-Recovery-Playbook.md](docs/404-Failure-Recovery-Playbook.md)**

---

# License

ref. [LICENSE](LICENSE)

---

# Contributing

ref. [CONTRIBUTING](CONTRIBUTING.md)

---

# Final Note

If you want a deterministic, YAML-first engine that runs cleanly in cron/containers and is easy to debug — use AetherFlow.
