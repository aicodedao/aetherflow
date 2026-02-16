# 22 — `external.process` Step (Backend Format)

Built-in step name: `external.process` (exact).

Source:
- `packages/aetherflow-core/src/aetherflow/core/builtins/steps.py` (`@register_step("external.process") class ExternalProcess`)
- `packages/aetherflow-core/tests/test_external_process_step.py`

Goal: run OS-level commands (dbt / spark-submit / shell / CLI tools) in an ops-friendly way:
- bounded logging options (inherit/capture/file/discard)
- timeout with SIGTERM → kill escalation
- retries (exit codes + timeout)
- success validation (marker / required files / forbidden files / globs)
- idempotency helpers (marker skip, atomic output dir)

---

## What this step actually is in code

Registry:
- registered as `external.process`
- class: `ExternalProcess(Step)`
- `required_inputs = {"command"}`

It runs:
- `subprocess.Popen(cmd, shell=shell, cwd=cwd_path, env=env, stdout=..., stderr=...)`
- waits with optional timeout; on timeout:
  - sends SIGTERM
  - waits `kill_grace_seconds`
  - then `kill()`

Returns a dict on success:
- `exit_code`
- `attempts`
- optional `stdout` / `stderr` if capture mode
- optional `log_file` if file logging enabled
- plus any keys you inject via `inputs.outputs`

If idempotency marker skip triggers, it returns a `StepResult` with `status=SKIPPED`.

---

## YAML schema (practical, matches implementation)

> This is the “what it accepts” schema based on the code. Field names below match `self.inputs.get(...)`.

### Required
- `command`: string OR list
  - if string → becomes `[command]`
  - if list → used as the full argv vector (recommended)

### Optional execution controls
- `args`: list
  - appended to `cmd` after `command`
- `shell`: bool (default `false`)
- `cwd`: string (optional)
  - resolved as a path:
    - absolute → used as-is
    - relative → resolved under job artifacts dir
- `timeout_seconds`: number (optional)
- `kill_grace_seconds`: int (default `15`)

### Environment
- `inherit_env`: bool (default `true`)
  - if `true`: start env from `ctx.env` (NOT the OS env directly)
  - if `false`: start from `{}` (clean env)
- `env`: dict (optional)
  - merged over base env
  - any `None` value becomes `""` (empty string)
- auto-injected env keys (always set if missing):
  - `AETHERFLOW_FLOW_ID`
  - `AETHERFLOW_RUN_ID`

### Logging
- `log`: dict (optional)
  - `stdout`: one of `inherit|capture|file|discard` (default `inherit`)
  - `stderr`: one of `inherit|capture|file|discard` (default `inherit`)
  - `max_capture_bytes`: int (default bounded; used only for capture)
  - `file_path`: string (optional; if not set, step chooses a default log file path when needed)

Notes:
- `capture` stores up to `max_capture_bytes` in memory and returns it in outputs.
- `file` writes logs to a file and returns `log_file` in outputs.

### Retry
- `retry`: dict (optional)
  - `max_attempts`: int (default `1`)
  - `sleep_seconds`: number (default `5`)
  - `retry_on_exit_codes`: list[int] (optional; if omitted, only non-success triggers fail without retry unless timeout retry enabled)
  - `retry_on_timeout`: bool (default `false`)

### Success validation
- `success`: dict (optional)
  - `exit_codes`: list[int] (default `[0]`)
  - `marker_file`: string (optional)
  - `required_files`: list[string] (optional)
  - `required_globs`: list[string] (optional)
  - `forbidden_files`: list[string] (optional)

Validation happens after process completion (and after atomic dir finalize, if used).
If validation fails → step fails with `RuntimeError("external.process outputs invalid: ...")`.

### Idempotency
- `idempotency`: dict (optional)
  - `strategy`: `none|marker|atomic_dir` (default `none`)

If `strategy: marker`:
- `marker_path`: string (optional)
- skip logic:
  - if marker exists AND success validation passes → return `StepResult(status=SKIPPED, output={"skipped": True, "marker": ...}, reason="marker_present")`

If `strategy: atomic_dir`:
- `temp_output_dir`: string (required)
- `final_output_dir`: string (required)
- behavior:
  - ensures temp dir is clean
  - sets env var `AETHERFLOW_OUTPUT_DIR` to temp dir (so your command writes into it)
  - after successful run + validation: moves temp contents into final dir

### Extra outputs (passthrough)
- `outputs`: dict (optional)
  - copied into result output payload (literal values)

---

## Best-practice YAML examples

### 1) Simple dbt run (env injection + timeout)

```yaml
- id: run_dbt
  type: external.process
  inputs:
    command: ["bash", "-lc", "dbt run"]
    cwd: "/tmp/repo"
    env:
      DBT_TARGET: "prod"
      DBT_PROFILES_DIR: "/tmp/profiles"
    timeout_seconds: 3600
    retry:
      max_attempts: 1
    success:
      exit_codes: [0]
````

### 2) Spark submit with atomic output dir (idempotent + safe rerun)

This matches the test coverage in `test_external_process_atomic_dir_success`.

```yaml
- id: run_spark
  type: external.process
  inputs:
    command:
      - spark-submit
      - --master
      - yarn
      - jobs/my_job.py
    idempotency:
      strategy: atomic_dir
      temp_output_dir: "out/.tmp_run"
      final_output_dir: "out/final"
    env:
      # Your script writes into this:
      # os.environ["AETHERFLOW_OUTPUT_DIR"]
      RUN_MODE: "prod"
    success:
      marker_file: "out/final/_SUCCESS"
    timeout_seconds: 7200
```

### 3) Clean env (do NOT inherit ctx.env) + capture logs

```yaml
- id: run_cli_clean
  type: external.process
  inputs:
    command: ["bash", "-lc", "echo hello && echo err 1>&2"]
    inherit_env: false
    env:
      PATH: "/usr/bin:/bin"
    log:
      stdout: capture
      stderr: capture
      max_capture_bytes: 200000
    timeout_seconds: 60
```

### 4) Retry on timeout (matches test behavior)

This matches `test_external_process_timeout_retry`.

```yaml
- id: run_slow
  type: external.process
  inputs:
    command: ["python", "-c", "import time; time.sleep(10)"]
    timeout_seconds: 0.5
    retry:
      max_attempts: 2
      retry_on_timeout: true
      sleep_seconds: 5
```

---

## Timeout behavior (exact)

If `timeout_seconds` is set and process exceeds it:

* step attempts SIGTERM
* waits `kill_grace_seconds` (default 15s)
* then kills the process
* if retries configured with `retry.retry_on_timeout: true`, it will retry until attempts exhausted
* otherwise it fails (raises `TimeoutError` in the tests)

---

## Idempotency guidance (what works well in practice)

* Prefer `idempotency.strategy: atomic_dir` for tools that write directories (Spark/ETL exports).
* Prefer `idempotency.strategy: marker` for tools that create a completion marker (dbt artifacts, `_SUCCESS`, etc.).
* If the external tool cannot tolerate overlap runs, wrap it with `with_lock`.

Example composition:

```yaml
- id: locked_dbt
  type: with_lock
  inputs:
    lock_key: "dbt_prod"
    ttl_seconds: 7200
    step:
      id: run_dbt
      type: external.process
      inputs:
        command: ["bash", "-lc", "dbt run"]
        cwd: "/tmp/repo"
        env:
          DBT_TARGET: "prod"
        success:
          exit_codes: [0]
```

---

## Reality check vs docstring

The `ExternalProcess` docstring mentions `{{run_id}}` rendering in paths, but the current `_resolve_path()` implementation does **not** render templates; it only resolves absolute vs artifacts-relative paths. If you need dynamic paths, compute them earlier (or rely on whatever your flow templating does before inputs reach the step).
