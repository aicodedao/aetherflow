# aetherflow 

[![GitHub Repo](https://img.shields.io/badge/GitHub-aetherflow-blue?logo=github)](https://github.com/aicodedao/aetherflow/tree/master/packages/aetherflow)
[![TestPyPI Version](https://img.shields.io/badge/dynamic/json?label=TestPyPI&url=https://test.pypi.org/pypi/aetherflow/json&query=$.info.version&cacheSeconds=10)](https://test.pypi.org/project/aetherflow-core/)
[![PyPI Version](https://img.shields.io/pypi/v/aetherflow?cacheSeconds=10)](https://pypi.org/project/aetherflow/)

`aetherflow` is a **convenience meta package**.

It installs:
- [aetherflow-core](https://github.com/aicodedao/aetherflow/tree/master/packages/aetherflow-core) (core engine + CLI `aetherflow`)
- [aetherflow-scheduler](https://github.com/aicodedao/aetherflow/tree/master/packages/aetherflow-scheduler) (scheduler + CLI `aetherflow-scheduler`)

It intentionally ships **no Python package code** itself (it’s just dependencies).

Use this if you want “the whole suite” with one install command.

---

## Install

```bash
pip install aetherflow
```

---

## What you get

CLIs:
- `aetherflow` (run flows)
- `aetherflow-scheduler` (cron scheduling)

Python modules:
- `aetherflow.core.*`
- `aetherflow.scheduler.*`

Quick sanity check:

```bash
python -c "import aetherflow.core; import aetherflow.scheduler"

aetherflow --help
aetherflow-scheduler --help
```

---

## Namespace package rule (important)

AetherFlow uses a **PEP 420 implicit namespace package** across multiple distributions.

That means:
- There should be **no** `aetherflow/__init__.py` shipped by these distributions.
- You generally should **not** do `from aetherflow import ...`.

Do:
- `from aetherflow.core.api import ...`
- `import aetherflow.core`
- `import aetherflow.scheduler`

---

## Docs (in this repository)

Canonical docs live in [Aetherflow Doumentation](https://github.com/aicodedao/aetherflow/tree/master/docs).

Start here:
- [Home Docs.](https://github.com/aicodedao/aetherflow/tree/master/docs/index.md)
