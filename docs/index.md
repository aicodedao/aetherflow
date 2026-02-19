# AetherFlow Documentation

[![GitHub Repo](https://img.shields.io/badge/GitHub-aetherflow-blue?logo=github)](https://github.com/aicodedao/aetherflow)
[![CI](https://github.com/aicodedao/aetherflow/actions/workflows/ci.yaml/badge.svg)](https://github.com/aicodedao/aetherflow/blob/master/.github/workflows/ci.yaml)
[![PyPI](https://img.shields.io/pypi/v/aetherflow-core?cacheSeconds=10)](https://pypi.org/project/aetherflow-core/)
[![Python](https://img.shields.io/badge/dynamic/json?label=Python&url=https://pypi.org/pypi/aetherflow-core/json&query=$.info.requires_python&cacheSeconds=10)](https://pypi.org/project/aetherflow-core/)
[![License](https://img.shields.io/badge/license-Internal-blue)](https://github.com/aicodedao/aetherflow/blob/master/LICENSE)


This is the **canonical documentation index** for AetherFlow.

The docs are structured so you can:
- start fast without drowning
- go deep when building production flows
- understand exactly how the engine behaves
- maintain the project safely

Two core ideas run through everything:

1) **Single Resolver Architecture**  
   One strict resolution pipeline handles templating + merge for:
   - resources
   - step inputs
   - step outputs  
   No parallel templating systems. No hidden evaluation layers.

2) **Strict templating contract**  
   Only:
   - `{{VAR}}`
   - `{{VAR:DEFAULT}}`  

   See → [99-strict-templating](99-strict-templating.md)

Anything else fails fast.

---

# Target Users

## Fast Reading Path

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

## New user

Start here (in this order):

1. **Fastest path to running something**
   → [93-flow-in-15-minutes](93-flow-in-15-minutes.md)

2. **Install → run → bundle → scheduler**
   → [01-quickstart](01-quickstart.md)

3. **Write safe YAML flows**
   → [10-flow-yaml-guide](10-flow-yaml-guide.md)

4. **Understand CLI behavior**
   → [90-cli-reference](90-cli-reference.md)

---

## Building production flows

Read these before shipping to prod:

- [02-architecture](02-architecture.md)
- [03-execution-model](03-execution-model.md)
- [04-skipping-and-gating](04-skipping-and-gating.md)
- [05-locking-guide](05-locking-guide.md)
- [99-strict-templating](99-strict-templating.md)
- [17-state](17-state.md)
- [16-observability](16-observability.md)
- [404-Failure-Recovery-Playbook](404-Failure-Recovery-Playbook.md)

These pages explain:
- deterministic execution
- resume semantics
- lock behavior
- strict templating failure modes
- how to debug safely at 2am

---

## Writing plugins

If you want custom connectors or steps:

- [18-plugins](18-plugins.md)
- [19-connectors](19-connectors.md)
- [20-steps](20-steps.md)
- [25-public-api-and-semver](25-public-api-and-semver.md)
- [21-reporting-guide.md](21-reporting-guide.md)
- [22-external-process-step.md](22-external-process-step.md)
- [23-builtins-catalog.md](23-builtins-catalog.md)

**Critical rule** - Only import from:

```python
from aetherflow.core.api import ...
```

Everything else is internal, and might be deprecated or not stable

---

# Getting Started

* [00-overview](00-overview.md)
* [01-quickstart](01-quickstart.md)
* [90-cli-reference](90-cli-reference.md)
* [93-flow-in-15-minutes](93-flow-in-15-minutes.md)

---

# Core Concepts

* [02-architecture](02-architecture.md)
* [03-execution-model](03-execution-model.md)
* [04-skipping-and-gating](04-skipping-and-gating.md)
* [05-locking-guide](05-locking-guide.md)
* [06-yaml-spec](06-yaml-spec.md)
* [99-strict-templating](99-strict-templating.md)

---

# Runtime & Execution

* [07-scheduler-yaml-guide](07-scheduler-yaml-guide.md)
* [08-manifest-and-bundles](08-manifest-and-bundles.md)
* [09-profiles-and-resources](09-profiles-and-resources.md)
* [11-envs](11-envs.md)
* [12-secrets](12-secrets.md)
* [13-envfiles](13-envfiles.md)
* [14-settings](14-settings.md)
* [15-concurrency](15-concurrency.md)
* [16-observability](16-observability.md)
* [17-state](17-state.md)
* [404-Failure-Recovery-Playbook](404-Failure-Recovery-Playbook.md)

---

# Extensibility / Authoring

* [10-flow-yaml-guide](10-flow-yaml-guide.md)
* [18-plugins](18-plugins.md)
* [19-connectors](19-connectors.md)
* [20-steps](20-steps.md)
* [22-external-process-step](22-external-process-step.md)
* [21-reporting-guide](21-reporting-guide.md)
* [23-builtins-catalog](23-builtins-catalog.md)

---

# Maintainer / Governance

For maintainers and release managers:

* [24-responsibility-model](24-responsibility-model.md)
* [25-public-api-and-semver](25-public-api-and-semver.md)
* [26-release-process](26-release-process.md)
* [27-publishing-to-pypi](27-publishing-to-pypi.md)
* [28-maintainer-release-checklist](28-maintainer-release-checklist.md)
* [29-renaming-checklist](29-renaming-checklist.md)
* [30-repo-files](30-repo-files.md)
* [31-labeling-guide](31-labeling-guide.md)
* [32-ci-cd.md](32-ci-cd.md)

These define:

* governance
* SemVer rules
* release safety
* repo structure constraints
* labeling discipline

# Reading Strategy

If overwhelmed:

1. Run something first → [93-flow-in-15-minutes.md](93-flow-in-15-minutes.md)
2. Understand what just happened → [03-execution-model.md](03-execution-model.md) + [17-state.md](17-state.md)
3. Learn how failures behave → [04-Failure-Recovery-Playbook.md](404-Failure-Recovery-Playbook.md)
4. Only then go into plugins and governance

