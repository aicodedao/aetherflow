# 99 — Strict Templating 

Source of truth:
- `packages/aetherflow-core/src/aetherflow/core/resolution.py`
- Exceptions: `packages/aetherflow-core/src/aetherflow/core/exception.py`
- Call sites: `packages/aetherflow-core/src/aetherflow/core/runner.py`, `.../validation.py`
- Settings flag: `packages/aetherflow-core/src/aetherflow/core/runtime/settings.py`

AetherFlow templating is intentionally **minimal and explicit**.  
If you try to use “smart” template syntax, it fails fast — by design.

---

# 1) Contract (syntax)

Only two token forms are supported:

- `{{PATH}}`
- `{{PATH:DEFAULT}}`

Where:

- `PATH = IDENT(.IDENT)*`
- `IDENT = [A-Za-z_][A-Za-z0-9_]*`
- whitespace inside braces is allowed:
    - `{{  env.DB_URL  }}`
    - `{{steps.extract.rows_json:[]}}`

Any other syntax MUST fail-fast with a `ResolverSyntaxError` and the message **exactly**:

> Unsupported templating syntax. Use {{VAR}} or {{VAR:DEFAULT}}

This string is hardcoded in `resolution.py` as `_UNSUPPORTED_MSG`.

---

# 2) Forbidden syntax (hard fail)

These legacy/templating patterns are explicitly forbidden anywhere in the string:

- `"$" + "{" + "..." + "}"`
- `"{" + "%" + "..." + "%" + "}"`
- `"{" + "#" + "..." + "#" + "}"`
- `"{" + "..." + "}"`

If any of those appear (even after rendering), the resolver raises `ResolverSyntaxError` with the same unsupported message.

Why:
- stops accidental Jinja/env interpolation from “leaking in”
- makes runs deterministic across environments
- prevents “silent magic” from creeping into YAML

---

# 3) Strict vs non-strict (what actually exists)

## Setting exists
There is a settings flag:

- `AETHERFLOW_STRICT_TEMPLATES` (default `"true"`)
- loaded into `Settings.strict_templates` in `runtime/settings.py`

## Reality check (current snapshot)
In this repo snapshot, the actual resolver entrypoints used by core are **always strict**:

- `resolve_resource_templates(..., strict=True)`
- `resolve_flow_meta_templates(..., strict=True)`
- `resolve_step_templates(..., strict=True)`

So:
- **invalid syntax → always fails**
- **missing keys without default → always fails**

The `_render_string(..., strict=...)` function supports non-strict behavior internally, but core does not currently wire `Settings.strict_templates` into these phase functions.

If/when the wiring is added, expected behavior should follow the internal design described below.

---

# 4) Missing variables behavior

For each token `{{PATH}}`:

- If `PATH` exists and resolves to a non-empty value → it renders as `str(value)`
- If missing (or resolves to empty string) and `DEFAULT` is provided → it renders `DEFAULT` (exact text after the first `:`)
- If missing and no default:
    - strict: raises `ResolverMissingKeyError(PATH)`
    - non-strict (not enabled by core today): renders empty string

Important nuance from code:
- empty string (`""`) is treated as “missing” for the contract.

---

# 5) Where templating applies (actual call sites)

Templating is applied in **two phases**, with different allowed roots.

## 5.1 Resource phase (resources/config/options)

Entry point:
- `resolve_resource(resource_dict, env_snapshot, set_envs_module)`

Template rendering applies to:
- `resource.config`
- `resource.options`

Allowed roots:
- only `env.*`

So resources may reference:

- `{{env.DB_URL}}`
- `{{env.DB_URL:sqlite:///local.db}}`

But may not reference:
- `steps.*`
- `job.*`
- `run_id`, `flow_id`, `result`

If you try, it fails with `ResolverSyntaxError` (unsupported message).

### Decode rules (resource-only)
Resources may specify a `decode:` section.
`resolve_resource()` will:
- expand env snapshot via `set_envs.expand_env(env_snapshot)` (if provided)
- render templates in config/options using env only
- optionally apply `set_envs.decode(value)` on selected leaf paths

Critical guardrail:
- decode paths cannot be “concatenated templates” (e.g. `"prefix-{{env.SECRET}}"`)
- if the raw value contains templating and is not a standalone token (`{{VAR}}`), it fails as unsupported syntax

This is deliberate: decode expects a single encoded value, not “string building”.

## 5.2 FlowMetadata phase 
Entry point:
- `resolve_flow_meta_templates(obj, runtime_ctx)`

Template rendering applies to:
- `flow` FlowMetadata in the flow yaml

Allowed roots:
- `env`       (env snapshot)

So resources may reference:

- `{{env.AETHERFLOW_WORK_ROOT:/tmp/work}}`

But cannot reference arbitrary roots. Anything outside the allowed root set fails fast.

## 5.3 Step phase (step inputs + declared outputs)

Entry point:
- `resolve_step_templates(obj, runtime_ctx)`

Used in runner for:
- `step.inputs` before executing the step
- `step.outputs` when promoting step outputs → job outputs

Allowed roots:
- `env`       (env snapshot)
- `steps`     (prior step outputs inside the same job)
- `job`       (`job.id`, `job.outputs`)
- `run_id`    (string)
- `flow_id`   (string)
- `result`    (current step result output dict; mainly for step.outputs promotion)
- `jobs`      (jobs output of the whole last jobs)

So step templates may reference:

- `{{env.SFTP_HOST}}`
- `{{steps.extract.artifact_path}}`
- `{{job.outputs.has_data:false}}`
- `{{run_id}}`
- `{{flow_id}}`
- `{{result.row_count:0}}`
- `{{jobs.first.outputs.files}}`

But cannot reference arbitrary roots. Anything outside the allowed root set fails fast.

---

# 6) Error taxonomy (real classes in code)

Defined in `aetherflow.core.exception`:

- Spec/schema/semantic validation:
    - `SpecError`

- Template syntax:
    - `ResolverSyntaxError`

- Missing keys in strict mode:
    - `ResolverMissingKeyError`

- Runtime failures:
    - step-specific exceptions (raised by step code)
    - `ConnectorError` for connector failures
    - `ReportTooLargeError` for reporting guardrails
    - external process errors for `external.process`

---

# 7) Best practices (the “don’t get paged at 2am” edition)

## Always provide defaults for optional env vars
Use:
- `{{env.MAYBE:}}`  (empty default)
- `{{env.TIMEOUT_SECONDS:30}}`

This avoids hard failures when env is intentionally absent.

## Prefer job gating over “template-driven branching”
If a job shouldn’t run without inputs, make it explicit:

- `when: jobs.probe.outputs.has_data == true`

Instead of letting templates explode mid-run.

## For “no data” paths, return SKIPPED instead of raising
Core runner supports:
- step returns `StepResult(status=SKIPPED, output={...})`
- plus `on_no_data: skip_job` to short-circuit the rest of the job

This keeps “no data” as a first-class state, not an exception storm.

## Don’t pass large payloads through templates
Templates are strings. For big data:
- stream to artifact file (`db_extract_stream`)
- consume file in downstream steps (Excel fill from file, uploads, etc.)

---

# 8) Quick examples

## OK: standalone token
- `password: "{{env.DB_PASSWORD}}"`

## OK: default value
- `dsn: "{{env.DSN:localhost:1521/XEPDB1}}"`

## FAIL: unsupported syntax
- `"$" + "{DB_PASSWORD}"`
- `"{" + "%" + "if ..." + "%" + "}"`
- `{{ env.DB_PASSWORD | lower }}`

## FAIL: unknown root (resource phase)
- `url: "{{steps.extract.artifact_path}}"`  # resources only allow env.*

## FAIL: missing key without default (strict)
- `url: "{{env.DOES_NOT_EXIST}}"`  # raises ResolverMissingKeyError
