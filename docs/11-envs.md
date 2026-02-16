# 11 — Envs (Env Snapshot, Modes, and Supported Environment Variables)

Primary sources:
- `aetherflow.core.runner` (runtime snapshot + bundle wiring)
- `aetherflow.core.runtime.settings` (settings env vars)
- `aetherflow.core.runtime.envfiles` (env_files loaders)
- `aetherflow.core.runtime.secrets` (decode + expand_env hook)
- `aetherflow.core.diagnostics.env_snapshot` (diagnostic snapshot builder; mirrors runtime logic)
- `aetherflow.core.validation` (strict env validation + template scanning)
- `aetherflow.core._architecture_guard` (strict architecture guard env var)
- `aetherflow.core.builtins.steps` (how subprocess env is built for `external.process`)

This document explains:
1) how AetherFlow builds a deterministic environment snapshot
2) how env is used by flow/job/step/resource templating
3) which `os.environ` variables are supported, what they do, and which modes affect them

---

## 1) Environment Snapshot (No `os.environ` Mutation)

### Runtime behavior (`run_flow`)

When you run a flow, the runner builds a deterministic snapshot:

- `env_snapshot = {k: str(v) for k, v in os.environ.items()}`
- optionally loads env files **into the snapshot** (opt-in)
- if a bundle manifest is used, it may wire additional keys into the snapshot
- the runner does **not** mutate `os.environ`
- the snapshot lives in `RunContext.env` and is treated as immutable for the run

This is visible directly in `aetherflow.core.runner.run_flow`.

### Env files (opt-in)

If `AETHERFLOW_ENV_FILES_JSON` is set, the runner loads env files into the snapshot:

- supported env file formats: `dotenv`, `json`, `dir` (directory-of-files)
- later files override earlier files deterministically
- each spec can optionally add a prefix to loaded keys

The loader implementation is in `aetherflow.core.runtime.envfiles`.

Example `AETHERFLOW_ENV_FILES_JSON` value (JSON string):

    [
      {"type": "dotenv", "path": "env/common.env", "optional": true, "prefix": ""},
      {"type": "json", "path": "env/overrides.json", "optional": true, "prefix": ""}
    ]

Notes:
- file paths are resolved as given (relative paths are relative to the current working directory)
- missing non-optional files raise an error

### Bundle manifest env files

If running with `--bundle-manifest`, the runner also supports manifest env files (loaded relative to the synced local bundle root).  
Implementation: `parse_env_files_manifest(...)` + `load_env_files(..., base_dir=bundle_root)`.

---

## 2) How Env Is Used (Flow / Job / Step / Resources)

### 2.1 Templating root: `env.*`

The environment snapshot is exposed to templating as `env`.

Practical consequence:
- anything templated in **resources**, **flow metadata**, **step inputs**, and **outputs promotion** can reference `{{ env.SOME_KEY }}`

Example in resources:

    resources:
      db_main:
        kind: db
        driver: postgres
        config:
          host: "{{ env.DB_HOST }}"
          user: "{{ env.DB_USER }}"
        decode:
          config:
            password: true

Example in FlowMetadata (in a sample flow yaml):

    version: 1
    flow:
      id: usecase1_sftp_to_smb_email
      description: "SFTP → unzip → transform → zip → SMB → email"
      workspace:
        # You can override this from the process environment.
        root: "{{env.AETHERFLOW_WORK_ROOT:/tmp/work}}"
        cleanup_policy: never
      state:
        backend: sqlite
        path: "/tmp/state/usecase1_sftp_to_smb_email.sqlite"

### 2.2 Where templating is applied

AetherFlow applies resolution/templating to (at least):
- resource `config` / `options` templates
- flow metatada templates
- step `inputs` templates
- step `outputs` promotion templates (job outputs)

Validation also scans templates and can optionally treat missing env keys as errors (see `AETHERFLOW_VALIDATE_ENV_STRICT` below).

### 2.3 Job gating and outputs

Job gating (`when`) is evaluated against a restricted context, typically including job outputs:

- `jobs.<job_id>.outputs.<key>`

Environment access in `when` is intentionally constrained (safe expression subset). Treat `when` as a gating DSL, not a full template engine.

### 2.4 Step exception: `external.process` subprocess env

AetherFlow does not mutate the Python process environment, but when running `external.process`, it constructs a subprocess environment map and sets:

- `AETHERFLOW_FLOW_ID` (defaulted to `ctx.flow_id`)
- `AETHERFLOW_RUN_ID` (defaulted to `ctx.run_id`)
- `AETHERFLOW_OUTPUT_DIR` (points at a temporary/atomic output directory used by the step)

These are injected **into the spawned process env**, not used as runner input configuration.

This behavior is implemented in `aetherflow.core.builtins.steps` (the `external.process` step).

---

## 3) Modes (`AETHERFLOW_MODE`): `internal_fast` vs `enterprise`

### Default and bundle behavior

- default mode is `internal_fast`
- when running with `--bundle-manifest`, the mode is derived from `manifest.mode` and written into the env snapshot as `AETHERFLOW_MODE`

Implementation: `aetherflow.core.runner.run_flow`

### What mode changes (current code)

#### enterprise mode
Enterprise mode implements a hard “don’t inherit untrusted plugin paths” policy:

- removes `AETHERFLOW_PLUGIN_PATHS` from the snapshot (hard deny)
- allows plugin paths only if explicitly set in manifest `paths.plugins`
- does **not** map `layout.plugins_dir` from the bundle into `AETHERFLOW_PLUGIN_PATHS`

This is explicitly coded in the runner and in diagnostics snapshot builder.

Enterprise mode allows only the trusted zip drivers.

#### internal_fast mode
- may map bundle `layout.plugins_dir` into `AETHERFLOW_PLUGIN_PATHS` (relative to local bundle root)
- does not hard-deny inherited plugin paths

Related: validation can enforce additional enterprise policies (e.g. archive allowlist) — see `06-yaml-spec.md`.

---

## 4) Supported `os.environ` Variables (What Exists in Code)

Below is the set of AetherFlow environment variables found in `aetherflow-core` code, what they do, and which mode affects them.

### 4.1 Runner / Snapshot / Bundle Wiring

- `AETHERFLOW_ENV_FILES_JSON`
  - Purpose: opt-in env file specs loaded into the env snapshot before execution
  - Used by: runner (`run_flow`) + diagnostics (`build_env_snapshot`)
  - Mode: same behavior in both modes

- `AETHERFLOW_MODE`
  - Purpose: execution policy mode (`internal_fast` / `enterprise`)
  - Used by: runner (bundle wiring + policy), downstream validation/policies
  - Mode: defines the mode itself

- `AETHERFLOW_PROFILES_JSON`
  - Purpose: inline profiles definition (JSON string) used for resource/profile overlays
  - Used by: runner + bundles/diagnostics tooling
  - Mode: same behavior in both modes

- `AETHERFLOW_PROFILES_FILE`
  - Purpose: path to profiles YAML file
  - Used by: runner + bundles/diagnostics tooling
  - Bundle wiring: if bundle layout defines `profiles_file`, runner sets this to `<bundle_root>/<profiles_file>`
  - Mode: same behavior in both modes

- `AETHERFLOW_PLUGIN_PATHS`
  - Purpose: plugin discovery search paths (comma-separated)
  - Used by: settings + plugin loader; also modified by bundle wiring
  - Mode impact:
    - `enterprise`: runner removes inherited value; only uses manifest trusted plugin paths
    - `internal_fast`: runner may set it to bundle `plugins_dir`

### 4.2 Settings (Loaded from env snapshot)

All settings are read from the env snapshot using `Settings.from_env(...)` in `aetherflow.core.runtime.settings`.

- `AETHERFLOW_WORK_ROOT`
  - Purpose: default work root (where run artifacts live)
  - Default: `/tmp/work`

- `AETHERFLOW_STATE_ROOT`
  - Purpose: default state root directory
  - Default: `/tmp/state`
  - Note: flow-level `flow.state.path` still controls the actual state DB location for a flow run; this is a default root used by tooling and conventions.

- `AETHERFLOW_LOCAL_ROOT_DIR`  
  - Purpose: default state local root directory
  - Default: `/tmp/work/bundle/<bundle_id>/active` (with bundle-manifest), or `/tmp/work` (without bundle-manifest)
  - Bundle wiring: if bundle is in use, or work_root in settings

- `AETHERFLOW_ACTIVE_DIR`  (bundle)
  - Purpose: default state local active directory
  - Default: `/tmp/work/bundle/<bundle_id>/active` (with bundle-manifest), or `/tmp/work` (without bundle-manifest)
  - Bundle wiring: if bundle is in use, or work_root in settings

- `AETHERFLOW_CACHE_DIR` (bundle)
  - Purpose: default state local cache directory
  - Default: `/tmp/work/bundle/<bundle_id>/cache` (with bundle-manifest), or `/tmp/work` (without bundle-manifest)
  - Bundle wiring: if bundle is in use, or work_root in settings

- `AETHERFLOW_LOG_LEVEL`
  - Purpose: logging level (e.g. INFO, WARNING, ERROR)
  - Default: `INFO`

- `AETHERFLOW_LOG_FORMAT`
  - Purpose: `text` (default) or `json` (one JSON object per line)
  - Default: `text`

- `AETHERFLOW_METRICS_MODULE`
  - Purpose: optional metrics sink module (expected to expose `METRICS`)
  - Default: unset

- `AETHERFLOW_PLUGIN_STRICT`
  - Purpose: plugin strictness behavior (boolean)
  - Default: `true`

- `AETHERFLOW_STRICT_TEMPLATES`
  - Purpose: strict template behavior (boolean)
  - Default: `true`

- `AETHERFLOW_CONNECTOR_CACHE_DEFAULT`
  - Purpose: default connector caching scope (`run`, `process`, or `none`)
  - Default: `run`

- `AETHERFLOW_CONNECTOR_CACHE_DISABLED`
  - Purpose: global disable connector caching (boolean)
  - Default: `false`

- `AETHERFLOW_SETTINGS_MODULE`
  - Purpose: importable module that provides `SETTINGS: dict` overrides
  - Default: unset
  - Note: applied after reading env snapshot defaults, before explicit overrides.

- `AETHERFLOW_SECRETS_MODULE`
  - Purpose: module providing `decode(value)->str` and optional `expand_env(env)->dict`
  - Default: unset

- `AETHERFLOW_SECRETS_PATH`
  - Purpose: file path to a Python module providing `decode(...)` and optional `expand_env(...)`
  - Default: unset

### 4.3 Validation / Diagnostics

- `AETHERFLOW_VALIDATE_ENV_STRICT`
  - Purpose: if `true`, missing env keys referenced in templates become **errors** (not warnings)
  - Used by: `aetherflow.core.validation`
  - Default: `false`
  - Mode: can be used in both modes; recommended in production/enterprise.

### 4.4 Architecture guard (dev/maintainer safety)

- `AETHERFLOW_STRICT_ARCH`
  - Purpose: disable strict architecture scan when set to `0`
  - Used by: `aetherflow.core._architecture_guard`
  - Default: enabled (`1`)
  - Mode: independent of `AETHERFLOW_MODE`
- `AETHERFLOW_STRICT_SANDBOX`
  - Purpose: enforce `allowlist_root` containment AND disallow symlink segments
  - Used by: __resolve_path
  - Default: enable (`True`)
  - Mode: independent of `AETHERFLOW_MODE`

### 4.5 Subprocess-only env keys (`external.process`)

These exist in code but are not used as runner inputs. They are injected into the spawned process env by `external.process`.

- `AETHERFLOW_FLOW_ID`
  - Purpose: available to subprocess for logging/metadata
- `AETHERFLOW_RUN_ID`
  - Purpose: available to subprocess for correlation
- `AETHERFLOW_OUTPUT_DIR`
  - Purpose: points to step-managed output directory (atomic/temporary)

---

## 5) Best Practices

1) Treat env snapshot as immutable truth
  - set env vars before starting the run
  - do not rely on runtime mutation

2) Use env files for reproducible configuration
  - prefer `AETHERFLOW_ENV_FILES_JSON` or bundle manifest `env.files`
  - keep the list ordered; later overrides earlier deterministically

3) Use profiles to separate “what the flow does” from “where it runs”
  - prefer `AETHERFLOW_PROFILES_FILE` in deployments
  - use `AETHERFLOW_PROFILES_JSON` for testing/CI overrides

4) In enterprise mode, don’t expect ambient plugin discovery
  - declare trusted plugin paths via manifest `paths.plugins`
  - do not rely on inherited `AETHERFLOW_PLUGIN_PATHS`

5) Turn on strict env validation in production
  - set `AETHERFLOW_VALIDATE_ENV_STRICT=true` to fail fast on missing env keys referenced by templates

---

## 6) Related Docs

- `09-profiles-and-resources.md` — profiles precedence + resource build pipeline
- `06-yaml-spec.md` — spec fields + semantic validation policies
- `08-manifest-and-bundles.md` — bundle wiring + fingerprinting + cache
- `99-strict-templating.md` — template syntax contract + strict behavior
- `18-plugins.md` — plugin API boundary and loading rules
