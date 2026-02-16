# 06 — YAML Spec (Current)

Source of truth:

- `aetherflow.core.spec`
- `aetherflow.core.validation`
- `aetherflow.scheduler.spec`

All YAML files are parsed into Pydantic models defined in `spec.py`, then passed through semantic validation in `validation.py`.

This document covers all currently defined specs:

1. Flow YAML (`FlowSpec`)
2. Profiles YAML (`ProfilesFileSpec`)
3. Bundle Manifest YAML (`BundleManifestSpec`)
4. Scheduler YAML (`SchedulerFileSpec`, `SchedulerItemSpec`)

If this document and `spec.py` ever disagree, **`spec.py` is authoritative**.

---

# 1. Flow YAML (`FlowSpec`)

The primary execution spec.

Minimal structure:

```yaml
version: 1

flow:
  id: string
  description: string            # optional

  workspace:
    root: "/tmp/work"
    cleanup_policy: on_success   # one of: on_success | always | never
    layout: {}                   # arbitrary mapping

  state:
    backend: sqlite
    path: "/tmp/state/state.db"

  locks:
    scope: flow                  # one of: none | job | flow
    ttl_seconds: 600

resources:
  <name>:
    kind: string
    driver: string
    profile: string            # optional
    config: {}
    options: {}
    decode: {}

jobs:
  - id: string
    description: string        # optional
    depends_on: [string, ...]
    when: string
    steps:
      - id: string
        type: string
        inputs: {}
        outputs: {}
        on_no_data: skip_job
```

---

## 1.1 `version`

Currently supported:

```
version: 1
```

Future versions may introduce incompatible changes.

---

## 1.2 `flow`

### `flow.id`

Unique identifier for the flow.

Used in:

- Workspace path structure
- State keys
- Logging context

Must be unique within the file.

---

### `flow.description` (optional)

Human-readable description.
No effect on execution.

---

## 1.3 `workspace`

```yaml
workspace:
  root: "/tmp/work"
  cleanup_policy: on_success | always | never
  layout: {}
```

### `root`

Base directory for artifacts.

Per-job directory:

```
<root>/<flow_id>/<job_id>/<run_id>/
```

---

### `cleanup_policy`

Controls job directory cleanup:

- `on_success`
- `always`
- `never`

---

### `layout`

Arbitrary mapping available to steps and plugins.
Core does not interpret this field.

---

## 1.4 `state`

```yaml
state:
  backend: sqlite
  path: "/tmp/state/state.db"
```

### `backend`

Currently supported:

- `sqlite`

Defines persistence mechanism.

---

### `path`

Path to SQLite database file.

State backend stores:

- Job status
- Step status
- Locks
- Run metadata

---

## 1.5 `locks`

```yaml
locks:
  scope: none | job | flow
  ttl_seconds: 600
```

Defines default lock behavior.

- `scope`
  - `none` (default)
  - `job`
  - `flow`

- `ttl_seconds`
  - Default TTL for lock acquisition

Most locking is performed explicitly using `with_lock`.

---

# 1.6 `resources`

Resources define external systems.

```yaml
resources:
  db_main:
    kind: database
    driver: duckdb
    profile: prod
    config: {}
    options: {}
    decode:
      config:
        password: true
```

Fields:

- `kind` – logical resource category
- `driver` – concrete implementation
- `profile` – optional profile mapping
- `config` – driver configuration
- `options` – runtime options
- `decode` – keys to decode via decode hook

All values pass through the resolver.

---

# 1.7 `jobs`

```yaml
jobs:
  - id: string
    description: string
    depends_on: []
    when: expression
    steps: []
```

---

### `id`

Unique within the flow.

---

### `description`

Optional metadata.

---

### `depends_on`

List of job IDs.

Rules:

- Must reference existing jobs
- Job runs only if all dependencies ended with `SUCCESS`
- Otherwise job becomes `BLOCKED`

---

### `when`

Boolean expression.

Supports restricted AST:

- `and`, `or`, `not`
- `== != > >= < <=`
- boolean literals
- access:
  - `jobs.<job_id>.outputs.<key>`

If false → job `SKIPPED`  
If invalid → runtime error

---

# 1.8 `steps`

```yaml
steps:
  - id: string
    type: string
    inputs: {}
    outputs: {}
    on_no_data: skip_job
```

---

### `id`

Unique within the job.

---

### `type`

Resolved via:

- Built-in registry
- Plugin registry

See:

→ `23-builtins-catalog.md`

---

### `inputs`

Step-specific configuration.
Resolved via templating pipeline.

---

### `outputs`

Mapping of:

```
job_output_key: template_expression
```

After step completion:

- Templates are rendered
- Outputs promoted to job-level outputs
- Accessible via `jobs.<job_id>.outputs.*`

---

### `on_no_data`

Currently supported:

- `skip_job`

If step returns `SKIPPED`, remaining steps are skipped.

---

# 2. Profiles YAML (`ProfilesFileSpec`)

Profiles define reusable resource configuration fragments.

Structure:

```yaml
<profile_name>:
  config: {}
  options: {}
  decode: {}
```

Example:

```yaml
prod:
  config:
    host: db.prod.local
  options:
    timeout: 30
  decode:
    config:
      password: true
```

Profiles are merged into resource definitions before connector creation.

Resolution order:

1. Base resource config
2. Profile overlay
3. Templating
4. Decode hook

Profiles enable environment-specific configuration without modifying flow YAML.

---

# 3. Bundle Manifest YAML (`BundleManifestSpec`)

Defines reproducible execution bundles.

Structure (simplified):

```yaml
version: 1
mode: enterprise | internal_fast

bundle:
  source:
    type: local                   # local | git | archive
    location: string

  layout:
    flows: string
    profiles: string
    plugins: string

resources: 
  
paths: 
  plugins: string
  
zip_drivers:
  - "..."

env_files: 
  - "..."

```

Bundle manifest responsibilities:

- Define source of flows/profiles/plugins
- Define layout mapping
- Control execution mode
- Provide env file references

Bundle sync:

```bash
aetherflow bundle sync --bundle-manifest bundle.yaml
```

Flow run with bundle:

```bash
aetherflow run flow.yaml --bundle-manifest bundle.yaml
```

Bundle execution ensures:

- Deterministic local cache
- Fingerprinting
- Controlled plugin loading

---

# 4. Scheduler YAML (`SchedulerFileSpec`, `SchedulerItemSpec`)

Scheduler is defined in its own spec.

Structure:

```yaml
timezone: Europe/Berlin

items:
  - id: string
    cron: "0 * * * *"
    flow_yaml: string
    flow: string              # optional
    flow_job: string          # optional
    bundle_manifest: string   # optional
    allow_stale_bundle: bool
    misfire_grace_time: int
```

Fields:

- `timezone` – IANA timezone
- `items` – scheduled entries

Each item defines:

- APScheduler job ID
- Cron expression
- Flow file
- Optional bundle manifest
- Optional flow/job filter
- Grace period for missed runs

Scheduler does not execute flow logic itself.
It delegates to `aetherflow-core`.

---

# 5. Semantic Validation (`validation.py`)

Beyond structural schema validation, semantic rules include:

- Job ID uniqueness
- Step ID uniqueness
- `depends_on` existence
- No cyclic job graph
- Valid template syntax
- Strict templating enforcement
- Optional strict env validation:
  - `AETHERFLOW_VALIDATE_ENV_STRICT=true`
- Enterprise mode restrictions:
  - Archive driver allowlist
  - Plugin path restrictions

Validation is designed to prevent production foot-guns before execution.

---

# 6. Strict Templating Contract

Template syntax:

```
{{ VAR }}
{{ VAR:DEFAULT }}
```

Invalid syntax → `ResolverSyntaxError`

Strict mode affects:

- Missing variables
- Invalid expressions
- Resolution behavior

See:

→ `99-strict-templating.md`

---

# 7. Design Principles of the Spec

The YAML spec is:

- Declarative
- Explicit
- Deterministic
- Validation-heavy
- Free of implicit behavior

The spec defines configuration, not business logic.

If behavior must change, change YAML — not the runner.
