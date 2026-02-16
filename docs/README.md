# AetherFlow 

This documentation set is the **canonical docs shipped with AetherFlow**.

It lives:
- in the repository
- inside published distributions (source and wheels)
- alongside the code it documents

The goal is simple:

Help you run **YAML-first workflows safely, deterministically, and debuggably**  
— without a UI, without a webserver, and without hidden magic.

If behavior changes in code, these docs must change with it.

---

# Fast Reading Path

If you only have 20–30 minutes, read in this order:

1) Project overview  
→ **[00-overview.md](00-overview.md)**  
What AetherFlow is (and is not).

2) Architecture decisions  
→ **[02-architecture.md](02-architecture.md)**  
Single Resolver Architecture, strict templating, config-over-code.

3) Install → run → bundle → scheduler  
→ **[01-quickstart.md](01-quickstart.md)**  
Get something running immediately.

4) Write real flows safely  
→ **[10-flow-yaml-guide.md](10-flow-yaml-guide.md)**  
Jobs, steps, gating, locks, retries, resume.

5) 15-minute practical flow  
→ **[93-flow-in-15-minutes.md](93-flow-in-15-minutes.md)**  
Zero theory. Just run it.

---

# What This Docs Set Covers

This documentation is aligned with:

- `aetherflow-core`
- `aetherflow-scheduler`
- built-in connectors and steps
- state, resume, locking, templating
- bundle + manifest behavior
- CLI commands and exit codes

If it’s described here, it must exist in:

```

packages/aetherflow-core/
packages/aetherflow-scheduler/

````

No speculative features.

---

# Namespace / Import Rules (Critical)

AetherFlow is a **namespace package** (PEP 420).

Correct imports:

```python
import aetherflow.core
import aetherflow.scheduler
````

Stable public API (for plugins / integrations):

```python
from aetherflow.core.api import ...
```

Do NOT use:

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

# Philosophy of These Docs

* YAML-first
* Deterministic runner
* Strict templating contract
* Config-over-code
* Explicit failure behavior
* State-backed resume
* No UI assumptions

If you want UI + orchestration + DAG visualizers, that is not this project.

If you want a boring, explainable, ops-grade YAML workflow engine, you’re in the right place.
