# 13 — Env Files (`runtime/envfiles.py`)

Primary sources:
- `aetherflow.core.runtime.envfiles`
- `EnvFileSpec` in `aetherflow.core.spec`
- env snapshot wiring in `aetherflow.core.runner`
- diagnostics mirror in `aetherflow.core.diagnostics.env_snapshot`

Env files are an **opt-in** mechanism to load environment defaults into the run’s immutable env snapshot.

They exist to make runs reproducible without relying on the ambient process environment.

Important:
- env files update the snapshot
- the runner does **not** mutate `os.environ`

---

## 1) Why Env Files Exist

Env files let you:

- keep environment defaults in version-controlled files
- load consistent env values across machines/containers
- avoid “works on my laptop” configuration drift
- layer overrides deterministically

Env files are applied to the env snapshot in a deterministic order (see Load Order).

---

## 2) Supported Types (`EnvFileSpec.type`)

`EnvFileSpec` supports three types.

### 2.1 `dotenv`

Format:
- `KEY=VALUE` per line
- UTF-8 text
- `#` comments supported
- strips simple quotes

Example:

DB_HOST="db.local"
DB_USER=app
# comment

Behavior notes:
- keys are parsed as raw strings
- values are strings after stripping basic quotes

---

### 2.2 `json`

Format:
- JSON file
- top-level object mapping keys to values:

{"KEY": "VALUE", "OTHER": "123"}

Rules:
- only top-level object is supported
- all values are coerced to string

---

### 2.3 `dir`

Format:
- a directory path
- each file name is a key
- file content is the value

Example:
```
#/tmp/env_dir/
DB_HOST   (file contains "db.local")
DB_PASS   (file contains "secret")
```

Rules:
- key = filename
- value = file content (as text, stripped)
- useful for containerized secret injection patterns

---

## 3) Env File Spec Fields (`EnvFileSpec`)

Conceptual schema:

type: dotenv | json | dir
path: "/tmp/path"
optional: false
prefix: ""

Field reference:

- `type` (required)
    - one of: dotenv, json, dir

- `path` (required)
    - file path (dotenv/json) or directory path (dir)

- `optional` (optional, default false)
    - if true: missing path is ignored
    - if false: missing path raises error (fail fast)

- `prefix` (optional, default "")
    - string prefix prepended to all loaded keys

Example:

type: json
path: "/tmp/env.json"
optional: true
prefix: "APP_"

This loads keys as:

APP_KEY, APP_OTHER, ...

---

## 4) Configuration via Environment

Env files are configured through:

AETHERFLOW_ENV_FILES_JSON

This must be a JSON string containing a list of `EnvFileSpec` dictionaries.

Example:

export AETHERFLOW_ENV_FILES_JSON='[
{"type":"dotenv","path":"/tmp/.env","optional":true},
{"type":"json","path":"/tmp/env.json","optional":true,"prefix":"APP_"}
]'

Rules:
- parsing errors fail fast
- invalid spec fails fast
- missing non-optional file fails fast

---

## 5) Load Order (Deterministic)

The runner constructs the final env snapshot in this order:

1) Start from process environment:

env_snapshot = dict(os.environ)

2) Apply env files from AETHERFLOW_ENV_FILES_JSON (if set)
    - loaded in list order
    - later entries override earlier entries
    - keys override any existing keys in snapshot

3) If running with a bundle manifest:
    - apply manifest `env_files` loaded relative to the active bundle root
    - these updates apply after AETHERFLOW_ENV_FILES_JSON
    - later values win deterministically

Net effect:
- base = os.environ
- then env file overlays
- then bundle env overlays (if active)

The last applied value wins.

---

## 6) Overwrite Semantics

Env file loading behaves like:

snapshot.update(loaded_values)

Meaning:
- keys already present in snapshot may be overwritten
- later overlays win
- all values are strings

This is intentional: env files act like explicit overrides.

---

## 7) Best Practices

1) Keep env files ordered and explicit
    - treat list order as “precedence”
    - keep the list short and readable

2) Use prefixes to avoid collisions
    - especially when loading multiple JSON files or directory envs

3) Prefer bundle env files for reproducible deployments
    - manifest `env_files` makes env part of the audited execution bundle
    - avoids relying on machine-local `.env` behavior

4) Enable strict env validation in CI
    - AETHERFLOW_VALIDATE_ENV_STRICT=true
    - fail fast when templates reference missing env keys

---

## 8) Related Docs

- `11-envs.md` — snapshot behavior + modes
- `12-secrets.md` — decode/expand hooks for secrets
- `08-manifest-and-bundles.md` — manifest env_files wiring
- `14-settings.md` — settings env vars
- `99-strict-templating.md` — template contract
