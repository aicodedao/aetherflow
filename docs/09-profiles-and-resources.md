# 09 — Profiles & Resources

Reproducible execution in AetherFlow depends on three layers:

1. An immutable environment snapshot (`ctx.env`)
2. Profiles (environment → config mapping)
3. Resources → connector instances (`ctx.connectors`)

Relevant modules:

- `aetherflow.core.runner`
- `aetherflow.core.spec`
- `aetherflow.core.connectors.manager`
- `aetherflow.core.resolution`

This document explains how configuration flows from environment to connectors in a deterministic way.

---

# 1) Environment Snapshot (`ctx.env`)

At the beginning of a run, the runner builds an immutable environment snapshot.

Conceptually:

- `env_snapshot = dict(os.environ)`
- All values coerced to `str`
- Optional env files loaded
- Optional bundle-derived overrides applied
- Optional `AETHERFLOW_MODE` injected when running with a bundle

Sources of environment data may include:

- `os.environ`
- Env files (from `AETHERFLOW_ENV_FILES_JSON` or manifest `env_files`)
- Bundle wiring
- Runtime flags

This snapshot is attached to:

```
RunContext.env
```

Key properties:

- `os.environ` is not mutated
- All resolution reads from the snapshot
- Snapshot is immutable for the duration of the run

This guarantees reproducibility and prevents side effects between runs.

---

# 2) Profiles

Profiles provide structured overlays for resource configuration.

They allow you to map:

```
Environment → resource config/options/decode
```

The runner loads profiles using the following precedence:

1. `AETHERFLOW_PROFILES_JSON` (JSON string)
2. `AETHERFLOW_PROFILES_FILE` (YAML file)
3. Fallback: `{}`

Profiles are resolved before connectors are instantiated.

Example profiles file:

```yaml
prod:
    config:
      host: db.prod.local
    options:
      connect_timeout: 30
    decode:
      config:
        password: true
```

Profiles enable:

- Explicit environment-based configuration
- Auditability (“where did this config come from?”)
- Clean separation between flow structure and deployment configuration

Profiles are defined in `ProfilesFileSpec` (`aetherflow.core.spec`).

---

# 3) Resources → Connector Instances

Flow YAML defines resources:

```yaml
resources:
    mydb:
    kind: db
    driver: postgres
    profile: prod
    config:
      host: "{{ env.DB_HOST }}"
    options:
      connect_timeout: 10
    decode:
      config:
        password: true
```

Each resource goes through a deterministic build pipeline.

---

## 3.1 Resolution Pipeline

For each resource:

1. Base resource dictionary loaded from FlowSpec
2. Profile overlay applied (if `profile` is set)
3. All fields passed through resolver (`aetherflow.core.resolution`)
4. Strict templating enforced (mode-dependent)

Resolution may reference:

- `env.*`
- job outputs
- other context values

Template syntax must follow strict contract (see `99-strict-templating.md`).

---

## 3.2 Config & Options Merge

Final resource config is built from:

- Flow-level `config`
- Profile-level `config`
- Flow-level `options`
- Profile-level `options`

Exact merge order is defined in connector manager logic.

The goal:

- Deterministic overlay
- No hidden defaults
- No implicit mutation

See: `19-connectors.md`

---

## 3.3 Secret Decode Hook

If a resource defines:

```yaml
decode:
  config:
    password: true

```

Then keys marked `true` are passed through the decode hook.

Decode behavior is configured via settings (e.g., custom decode module/path).

This allows:

- Encrypted secrets in YAML
- Late decode during resolution
- Controlled secret expansion

Decode happens before connector instantiation.

---

## 3.4 Connector Instantiation

After resolution:

- Connector manager selects implementation based on `kind` + `driver`
- Registry resolves built-in or plugin connector
- Connector instance created
- Optional caching applied (if enabled)

Connector instances are stored in:

```
ctx.connectors["mydb"]
```

Connectors are thin wrappers around drivers/transports.

They should:

- Avoid global state
- Expose minimal primitives (client/session/execute)
- Remain idempotent where possible

---

# 4) Deterministic Configuration Contract

The full configuration chain is:

OS env / env files
↓
env snapshot (immutable)
↓
profiles overlay
↓
resource resolution (strict templating)
↓
decode hook
↓
connector instantiation
↓
ctx.connectors available to steps

At no point is `os.environ` mutated.

All behavior is derived from:

- YAML
- Profiles
- Environment snapshot
- Bundle wiring (if active)

This is what makes runs reproducible and auditable.

---

# 5) Relationship to Connectors

Resources define configuration.

Connectors implement behavior.

For full details on:

- Connector lifecycle
- Caching
- Driver resolution
- Writing custom connectors

See:
→ `19-connectors.md`

