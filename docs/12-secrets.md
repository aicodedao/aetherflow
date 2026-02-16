# 12 — Secrets (Decode + Expand Chain)

Primary sources:
- `aetherflow.core.runtime.secrets`
- secrets hook loading and wiring in `aetherflow.core.runner`

Goal:
Allow users to plug in a “secrets provider” (your `set_envs.py`-style decoder/expander) while keeping the runner deterministic and safe:

- secrets are resolved from the immutable env snapshot
- decoding is explicit (only for marked fields)
- the runner does **not** mutate `os.environ`

---

## 1) What “Secrets” Means in AetherFlow

AetherFlow does not ship a vault product.

Instead, it provides a small hook interface:

- `expand_env(env_snapshot)` for preprocessing the env snapshot (optional)
- `decode(value)` for decoding encrypted/encoded values (required)

This hook is used for:
- decoding passwords or tokens embedded in environment variables or YAML
- expanding derived env keys (e.g., build connection strings)
- applying organization-specific secret handling logic without modifying core

The hook is executed inside the runner and should behave like a pure function:
- no global side effects
- no logging of secret values
- no `os.environ` mutation

---

## 2) Configuration

You can configure secrets provider in two ways.

Precedence rule:
- module wins over path (if both are set)

### Option A — Importable module (preferred)

Set:

AETHERFLOW_SECRETS_MODULE=<importable.module>

Your module must expose:

- decode(value: str) -> str
- expand_env(env: dict[str, str]) -> dict[str, str]

Example (module interface):

def decode(value: str) -> str:
...

def expand_env(env: dict[str, str]) -> dict[str, str]:
...

### Option B — Python file path

Set:

AETHERFLOW_SECRETS_PATH=/abs/or/rel/path/to/set_envs.py

The file must expose the same interface:

- decode(value: str) -> str
- expand_env(env: dict[str, str]) -> dict[str, str]

---

## 3) End-to-End Execution Flow (What Actually Happens)

This is the real runtime chain:

1) Runner builds the initial env snapshot:

env_snapshot = {k: str(v) for k, v in os.environ.items()}

2) Runner loads the secrets provider (module or path).

3) If provider defines expand_env:
    - runner calls expand_env(env_snapshot)
    - the provider must return a **new dict** (or an updated dict)
    - runner replaces snapshot with the returned value
    - runner still does NOT mutate os.environ

4) Resource resolution and connector build:
    - when the runner builds a resource, it checks the resource’s `decode` mapping
    - for any field marked `true`, the runner calls:

decode(value)

Important: YAML does NOT require wrappers like `ENC(...)`.  
Decoding is driven solely by the resource spec’s `decode` map.

---

## 4) How Decoding Is Applied (Resource-Level)

Resource example:

```yaml
resources:
    mydb:
    kind: db
    driver: postgres
    config:
      host: "{{ env.DB_HOST }}"
      password: "{{ env.DB_PASSWORD }}"
    decode:
      config:
        password: true
```

Rules:

- decode is applied only for keys explicitly marked `true`
- decode is executed at runtime during resource build
- decode receives a string and must return a string
- decode is NOT applied globally to all env vars

This design prevents accidental secret decoding and keeps behavior auditable.

---

## 5) Precedence Rules

### Provider selection

If both are set:

- AETHERFLOW_SECRETS_MODULE
- AETHERFLOW_SECRETS_PATH

Then the module is used and the path is ignored.

### Scope of decode

- decode is applied only to keys explicitly marked in `resources.<name>.decode`
- unmarked fields are never decoded

---

## 6) Failure Behavior

Secrets handling is “fail fast”.

- If the provider cannot be loaded (bad module/path):
    - raise error
    - run fails immediately

- If expand_env raises:
    - raise error
    - run fails immediately

- If decode raises:
    - raise error
    - run fails immediately

This is intentional: secrets handling must be deterministic and correct, not “best effort”.

---

## 7) Security Notes and Modes

AetherFlow modes:

- `internal_fast`
- `enterprise`

Enterprise mode mainly enforces:
- trusted plugin path behavior
- archive driver allowlists (validated elsewhere)

Secrets hooks still run if configured in either mode.

You are responsible for writing a safe provider:

Do:
- treat inputs/outputs as sensitive
- keep functions pure (no global state)
- return new dicts from expand_env
- avoid printing or logging secrets

Do not:
- mutate os.environ
- write secrets to disk or logs
- leak secrets via exceptions or debug output

AetherFlow intentionally does not try to “protect you from yourself” here; it makes the hook explicit.

---

## 8) Practical Patterns

### Pattern A — Decode only selected fields

Use `decode` mapping in resources for exact control.

### Pattern B — Expand env once, then decode selectively

Use expand_env to derive safe convenience keys:

- build DSNs
- normalize env naming
- apply organization defaults

Then decode only the minimum required fields.

---

## 9) Related Docs

- `11-envs.md` — env snapshot behavior and mode wiring
- `09-profiles-and-resources.md` — how resources are built and resolved
- `06-yaml-spec.md` — resource schema and decode mapping
- `18-plugins.md` — plugin loading policies (enterprise vs internal_fast)
