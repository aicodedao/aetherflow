# 30 — Repo Files / Folders Map (Backend Format)

This document maps the repo layout and explains what each folder/file does.

---

# 1) Repo Root (expected layout)

These are the *recommended* repo-root folders for AetherFlow.  

- `README.md`
    - project overview, quickstart, install matrix (core/scheduler/meta), compatibility notes
- `docs/`
    - canonical documentation (the pages we’re writing: Reporting, Builtins Catalog, Release, etc.)
- `demo/`
    - end-to-end smoke flows + scheduler configs (should be runnable with zero/low external deps)
- `packages/`
    - monorepo distributions 
- `.github/` or CI config
    - test + build + publish pipelines

---

# 2) `packages/` 

contains exactly these distributions:

- `packages/aetherflow-core/`
- `packages/aetherflow-scheduler/`
- `packages/aetherflow/` (meta)

All distributions use **src layout**:
- `packages/<dist>/src/...`

---

# 3) Distribution: `packages/aetherflow/` (meta package)

**Purpose**
- “Batteries included” meta distribution.
- Depends on `aetherflow-core` + `aetherflow-scheduler`.
- Typically provides the main user-facing `aetherflow` CLI entrypoint (depending on how you wire scripts).

**Files**
- `packages/aetherflow/pyproject.toml`
    - metadata + dependencies + console scripts (if defined here)
- `packages/aetherflow/README.md`
    - meta package explanation, install instructions

**Notes**
- This package usually contains little/no runtime code; it exists to give users a single install target.

---

# 4) Distribution: `packages/aetherflow-scheduler/`

**Purpose**
- Scheduler wrapper around the core runner.
- Provides scheduling / triggering surface + scheduler CLI.

**Top-level files**
- `packages/aetherflow-scheduler/pyproject.toml`
    - defines dist name, depends on `aetherflow-core`
    - defines `aetherflow-scheduler` console script (expected)
- `packages/aetherflow-scheduler/README.md`
    - scheduler usage, config examples

**Source tree**
- `packages/aetherflow-scheduler/src/aetherflow/scheduler/`
    - `__init__.py`
        - scheduler package init + version export
    - `cli.py`
        - scheduler CLI entrypoint: `aetherflow.scheduler.cli:main` (expected)
    - `scheduler.py`
        - scheduler implementation glue (APScheduler wrapper layer)
    - `runner.py`
        - thin adapter that calls core runner with scheduler semantics

**Tests**
- `packages/aetherflow-scheduler/tests/test_import_scheduler.py`
    - import-level smoke (ensures packaging + namespace works)

---

# 5) Distribution: `packages/aetherflow-core/` (this is the real engine)

**Purpose**
- Core runtime: spec parsing, validation, resolution, runner, state/resume, connectors/steps managers
- Builtins registry (connectors + steps)
- Core CLI

**Top-level**
- `packages/aetherflow-core/pyproject.toml`
    - dist metadata + optional extras (excel/parquet/etc)
    - console scripts for core CLI (if defined here)
- `packages/aetherflow-core/README.md`
    - core overview + quickstart + constraints
- `packages/aetherflow-core/tests/`
    - contract + guardband tests (ensures “boring + deterministic” constraints stay enforced)

---

## 5.1) Core source layout (`packages/aetherflow-core/src/aetherflow/core/`)

### Public API surface
- `api/__init__.py`
    - **ONLY public import surface** for plugin authors and integrators:
        - `register_step`, `register_connector`
        - `list_steps`, `list_connectors`
        - any stable base contracts intentionally exported

### Builtins registry
- `builtins/`
    - `connectors.py`
        - built-in connector implementations + registrations
    - `steps.py`
        - built-in step implementations + registrations
    - `register.py`
        - helper that registers all builtins into the registry (single call site)

### CLI
- `cli.py`
    - `aetherflow` CLI implementation (validate/run/etc)
    - loads runtime settings + registers builtins + executes commands

### Runner + execution
- `runner.py`
    - orchestration: step execution ordering, resume semantics, error surfaces
- `context.py`
    - step context object: connectors access, state access, run metadata, env overlay
- `spec.py`
    - flow/job spec models (parsed YAML → structured representation)
- `validation.py`
    - semantic validation (schema checks, step references, resource references)
- `resolution.py`
    - resolves templates + resources + step dependencies into an executable plan

### State / resume
- `state.py`
    - state store abstraction + resume bookkeeping
    - run id, step status persistence, outputs snapshots

### Connectors framework
- `connectors/`- 
    - `__init__.py`
        - connector package exports
    - `base.py`
        - connector base contract (init/config/close patterns)
    - `manager.py`
        - connector lifecycle: instantiate, cache, close all

### Steps framework
- `steps/`
    - `base.py`
        - step base contract: input reading, output shaping, standard errors
    - `_io.py`
        - common IO helpers used by steps (artifact path helpers, atomic writes, etc.)
    - `__init__.py`
        - step package exports

### Runtime bootstrapping
- `runtime/`
    - `_bootstrap.py`
        - runtime initialization glue (loading settings, env injection)
    - `settings.py`
        - settings model + profile behavior (`internal_fast` vs `enterprise` knobs live here conceptually)
    - `secrets.py`
        - secrets decode hooks / env expansion / redaction rules
    - `envfiles.py`
        - `.env` loading / environment snapshot composition

### Plugins
- `plugins.py`
    - plugin loading rules (paths, manifests, allow/deny behavior depending on profile)
    - this is where “trusted code only” vs “dev convenience” tends to be enforced

### Observability + diagnostics
- `observability.py`
    - minimal hooks: lifecycle events, log shaping, structured metadata
- `diagnostics/`
    - `env_snapshot.py`
        - capture environment snapshot for debugging / reproducibility
    - `__init__.py`
        - diagnostics helpers

### Concurrency / safety guard
- `concurrency.py`
    - small concurrency primitives (thread/process safe helpers used by runner/locks)
- `_architecture_guard.py`
    - “guardband” rules: prevents legacy patterns / enforces repo architectural constraints

### Misc
- `bundles.py`
    - dependency bundles / extras logic (e.g. `[reports]`, `[excel]`, etc.)
- `exception.py`
    - core exception types (`ConnectorError`, `StepError`, etc.)
- `__init__.py`
    - version + package metadata exports

---

## 5.2) Core test suite (what it covers)

`packages/aetherflow-core/tests/` includes:

- CLI validation + bundle smoke:
    - `test_cli_validate.py`
    - `test_cli_bundle_sync.py`
    - `test_bundle_sync.py`
- Contracts / public API:
    - `test_public_api.py`
    - `test_public_api_contract.py`
    - `test_resolution_contract_v2.py`
- Builtins correctness:
    - `test_reporting_steps.py` (Excel reporting)
    - `test_zip_steps.py` (zip/unzip)
    - `test_mail_connector.py`
    - `test_external_process_step.py`
- Guardbands (keep repo boring):
    - `test_docs_guardband_no_legacy.py`
    - `test_guardband_no_legacy_strings.py`
- Observability + diagnostics:
    - `test_observability.py`
    - `test_diagnostics.py`
- Execution controls:
    - `test_skip_and_when.py` (skip/when semantics)
    - `test_validation_semantic.py`

These tests act like enforcement for the “Responsibility Model”:
core stays deterministic, and behavior changes must be explicit.

---

# 6) Namespace package note (PEP 420)

This repo uses a namespace-style layout:
- `aetherflow-core` provides `aetherflow/core/...`
- `aetherflow-scheduler` provides `aetherflow/scheduler/...`

Avoid adding a top-level `aetherflow/__init__.py` in sub-dists unless you intentionally want to stop being a namespace package.

---

# 7) Quick mental model

- **core** = runtime engine + registries + builtins + CLI
- **scheduler** = “trigger/run core on a schedule” + scheduler CLI
- **meta** = “one pip install to get everything”

If you’re debugging a run:
- start at `core/cli.py` → `core/runner.py` → builtins (`core/builtins/*`) → managers (`core/connectors/manager.py`)
