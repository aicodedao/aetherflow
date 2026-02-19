# aetherflow-core

[![GitHub Repo](https://img.shields.io/badge/GitHub-aetherflow-blue?logo=github)](https://github.com/aicodedao/aetherflow/tree/master/packages/aetherflow-core)
[![TestPyPI Version](https://img.shields.io/badge/dynamic/json?label=TestPyPI&url=https://test.pypi.org/pypi/aetherflow-core/json&query=$.info.version&cacheSeconds=10)](https://test.pypi.org/project/aetherflow-core/)
[![PyPI Version](https://img.shields.io/pypi/v/aetherflow-core?cacheSeconds=10)](https://pypi.org/project/aetherflow-core/)

`aetherflow-core` is a **YAML-first workflow engine** for ops-style ETL/ELT/automation: run-once jobs you can schedule anywhere (cron, Kubernetes, Airflow, Nomad, systemd, etc.).

It focuses on being:
- **Deterministic**: given the same inputs, do the same thing
- **Composable**: Flow → Job → Step, with clear boundaries
- **Safe by default**: retries, timeouts, idempotency helpers, structured results
- **Extensible**: add custom steps/connectors via a stable public API

This distribution ships the CLI **`aetherflow`**.

---

## Install

```bash
pip install aetherflow-core[all]
```

Minimal install (if you want to control optional deps yourself):

```bash
pip install aetherflow-core
```

Python: **3.10+**.

---

## Quickstart (run a flow)

Create a file `flow.yaml`:

```yaml
version: 1

flows:
  hello_flow:
    jobs:
      main:
        steps:
          - id: hello
            type: external.process
            command: ["python", "-c", "print('hello from aetherflow')"]
```

Run it:

```bash
aetherflow run --flow-yaml flow.yaml --flow-job main
```

> Tip: the built-in step type is **`external.process`** (not `external_process`).

---

## Concepts (how to think about it)

- **Flow**: top-level unit (a collection of jobs)
- **Job**: a run-once unit of work (a list or graph of steps)
- **Step**: one action (shell/process, connector ops, custom plugin step, etc.)
- **Resources**: named configs used by steps/connectors (e.g., DB connection profiles)
- **State / resume**: persistent run state for reliability (if enabled/configured)
- **Locks**: prevent overlapping executions when you run in parallel environments

Core stays intentionally run-once. Scheduling is handled by `aetherflow-scheduler` (separate package).

---

## CLI

```bash
aetherflow run --help
aetherflow run --flow-yaml flow.yaml --flow-job main
```

Full command reference (in this repo):
- [Cli. Reference](https://github.com/aicodedao/aetherflow/tree/master/docs/90-cli-reference.md)

---

## Public API (for plugins / integrations)

If you are writing plugins or integrating AetherFlow programmatically, **only import from**:

```python
from aetherflow.core.api import (
    FlowSpec, JobSpec, StepSpec, 
    Step, StepResult,
    register_step, register_connector,
    Settings, RunContext,
)
```

Everything outside `aetherflow.core.api` is internal and may change without notice.

Public API and SemVer policy:
- `aetherflow/docs/25-public-api-and-semver.md`

---

## Extending AetherFlow 

High-level flow:
1) Implement a `Connector`, `Step` subclass (or a compatible callable/factory, depending on your plugin style).
2) Register it with `register_connector(...)`.
2) Register it with `register_step(...)`.
3) Reference it by `type:` in YAML.

Plugin guide:
- [Plugins](https://github.com/aicodedao/aetherflow/tree/master/docs/18-plugins.md)
- [Connectors](https://github.com/aicodedao/aetherflow/tree/master/docs/19-connectors.md)
- [Steps](https://github.com/aicodedao/aetherflow/tree/master/docs/20-steps.md)

---

## YAML spec & guides

Start here:
- [Yaml Spec.](https://github.com/aicodedao/aetherflow/tree/master/docs/06-yaml-spec.md)
- [Flow yaml guide](https://github.com/aicodedao/aetherflow/tree/master/docs/10-flow-yaml-guide.md)
- [Flow in 15-minutes](https://github.com/aicodedao/aetherflow/tree/master/docs/93-flow-in-15-minutes.md)

Built-in catalog:
- [Step - External process](https://github.com/aicodedao/aetherflow/tree/master/docs/22-external-process-step.md)
- [Builtins Catalog](https://github.com/aicodedao/aetherflow/tree/master/docs/23-builtins-catalog.md)

---

## Docs (in this repository)

Canonical docs live in [Aetherflow Doumentation](https://github.com/aicodedao/aetherflow/tree/master/docs).

Start here:
- [Home Docs.](https://github.com/aicodedao/aetherflow/tree/master/docs/index.md)

If you need scheduling, install **[aetherflow-scheduler](https://github.com/aicodedao/aetherflow/tree/master/packages/aetherflow-scheduler)**.
