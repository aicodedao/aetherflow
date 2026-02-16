# 14 — Settings (`runtime/settings.py`)

Source of truth:

- `aetherflow.core.runtime.settings.Settings`
- `aetherflow.core.runtime.settings.load_settings`

This document describes how runtime settings are loaded and which environment variables are supported.

If documentation and code disagree, `runtime/settings.py` is authoritative.

---

# 1) Design Principles

## Snapshot-Based Configuration

Settings are loaded from the **environment snapshot**, not directly from `os.environ`.

Typical flow:

1. Runner builds immutable env snapshot.
2. `Settings.from_env(env_snapshot)` parses supported keys.
3. Settings are frozen for the duration of the run.

If `load_settings()` is called without a snapshot:

- it builds a snapshot from `os.environ`
- this is for backward compatibility
- the preferred path is snapshot-based execution

The framework does **not mutate `os.environ`**.

---

# 2) Core Path Settings

### AETHERFLOW_WORK_ROOT

- Purpose: base directory for run artifacts
- Default: `/tmp/work`
- Exposed as: `Settings.work_root`

Used by:
- Runner to determine workspace base
- Bundle cache layout
- Artifact directory composition

---

### AETHERFLOW_STATE_ROOT

- Purpose: default root for state-related paths
- Default: `/tmp/state`
- Exposed as: `Settings.state_root`

Note:
Flow-level `flow.state.path` ultimately determines the SQLite DB path for a given run.  
`AETHERFLOW_STATE_ROOT` is a default root used by tooling and conventions.

---

# 3) Plugin Settings

### AETHERFLOW_PLUGIN_PATHS

- Comma-separated list of filesystem paths
- Used for plugin discovery
- Exposed as: `Settings.plugin_paths`

Behavior:
- Paths are parsed and normalized
- Used by plugin loader to register steps/connectors

Mode interaction:
- In `enterprise` mode, inherited plugin paths may be stripped by the runner
- In `internal_fast`, plugin paths may be inherited or bundle-mapped

---

### AETHERFLOW_PLUGIN_STRICT

- Default: `true`
- Exposed as: `Settings.plugin_strict`

If `true`:
- Plugin load errors fail the run immediately.

If `false`:
- Plugin errors may be tolerated (depending on loader behavior).

Recommended:
- Keep `true` in production.

---

# 4) Strict Templating

### AETHERFLOW_STRICT_TEMPLATES

- Default: `true`
- Exposed as: `Settings.strict_templates`

If `true`:
- Missing template variables → error
- Invalid template syntax → error

If `false`:
- Resolution may be more permissive (depending on resolver implementation)

See:
- `99-strict-templating.md`

---

# 5) Logging & Observability

### AETHERFLOW_LOG_LEVEL

- Default: `INFO`
- Exposed as: `Settings.log_level`

Controls runtime log verbosity.

---

### AETHERFLOW_LOG_FORMAT

- Default: `text`
- If set to `json`, logs are emitted as:
  - one JSON object per line

Exposed as: `Settings.log_format`

JSON mode is recommended for:
- Structured log ingestion
- Centralized observability pipelines

---

### AETHERFLOW_METRICS_MODULE

- Purpose: optional metrics sink
- Value: importable module exposing:

  METRICS: MetricsSink

Exposed as: `Settings.metrics_module`

If set:
- The runner imports the module
- The `METRICS` object is used for emitting metrics

See:
- `16-observability.md`

---

# 6) Secrets Hooks

These are consumed by the runner but referenced through settings.

### AETHERFLOW_SECRETS_MODULE

- Importable module path
- Must expose:
  - decode(value: str) -> str
  - expand_env(env: dict[str,str]) -> dict[str,str]

### AETHERFLOW_SECRETS_PATH

- File path to Python module
- Same required interface

Precedence:
- Module wins over path

See:
- `12-secrets.md`

---

# 7) Settings Module Override

### AETHERFLOW_SETTINGS_MODULE

- Importable module
- Must expose:

  SETTINGS: dict

Purpose:
- Override default settings programmatically
- Apply centralized configuration logic

Load order (conceptually):

1. Build Settings from env snapshot
2. If settings module defined:
  - import module
  - merge `SETTINGS` dict into existing settings

Use carefully:
- This affects runtime-wide configuration.

---

# 8) Connector Cache Defaults

### AETHERFLOW_CONNECTOR_CACHE_DEFAULT

- Controls default connector cache scope
- Possible values (from code):
  - `run`
  - `process`
  - `none`
- Default: `run`

Exposed as: `Settings.connector_cache_default`

Meaning:
- `run` → cache connectors within a single run
- `process` → cache across runs within same Python process
- `none` → no caching

---

### AETHERFLOW_CONNECTOR_CACHE_DISABLED

- Default: `false`
- If `true`, disables connector caching globally

Exposed as: `Settings.connector_cache_disabled`

Useful for:
- Debugging
- Testing connector initialization behavior

---

# 9) Architecture Guard (Related but Separate)

Not strictly a runtime setting, but environment-controlled:

### AETHERFLOW_STRICT_ARCH

- Default: enabled
- If set to `0`, disables strict architecture guard
- Used by internal architecture enforcement logic

This is mainly relevant for maintainers.

---

# 10) Snapshot Discipline (Important for Plugin/Step Authors)

Settings and runner follow snapshot-based execution.

If you are writing:

- Plugin
- Step
- Connector

You must:

- Read configuration from provided context (`ctx.env`, `Settings`)
- Never mutate `os.environ`
- Never rely on environment variables changing mid-run

All configuration should be:

- Explicit
- Derived from snapshot
- Deterministic

See:
- `11-envs.md`
- `20-steps.md`

---

# 11) Summary

Settings are:

- Loaded from env snapshot
- Immutable during run
- Explicitly defined via supported `AETHERFLOW_*` variables
- Mode-aware (enterprise vs internal_fast)
- Designed for deterministic, CLI-first execution

The core principle:

Configuration comes from environment snapshot.
Behavior must not depend on ambient mutable process state.


