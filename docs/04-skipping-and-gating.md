# 04 — Skipping & Gating

AetherFlow treats **“no data”** as a valid outcome, not automatically a failure.

This is the foundation for production-grade “nothing new today” workflows:
- avoid noisy failures
- avoid wasting compute
- keep downstream steps boring and deterministic

---

## 1) Step SKIP (No Data)

A step may return `STEP_SKIPPED` (for example: a query returns 0 rows, or a remote directory is empty).

When a step returns `STEP_SKIPPED`:

- the runner records the step status as `SKIPPED` in the state backend
- resume behavior applies the same way as `SUCCESS` (the runner will not re-run it)

---

### `on_no_data`

Many step specs support an explicit policy:

- `on_no_data: skip_job` → short-circuit the remainder of the job

If configured, and the step returns `SKIPPED`, the runner:

1. marks the remaining steps in that job as `SKIPPED`
2. marks the job as `SKIPPED` if all executed steps are either `SUCCESS` or `SKIPPED`

Best practice: put a **probe step up-front** (DB check, SFTP list, API “new items” check) and skip the rest of the job when there is nothing new.

Example:

```yaml
steps:
  - id: probe
    type: check_items
    inputs:
      items: ""
    on_no_data: skip_job

  - id: extract
    type: db_extract
    inputs:
      resource: db_main
      sql: "SELECT 1 AS ok"
      output: out.tsv
```

When the probe returns `SKIPPED`, the runner short-circuits and the remaining steps become `SKIPPED`.

Probe steps should return structured outputs such as:

```json
{"has_data": false, "count": 0, "reason": "no new rows"}
```

---

## 2) Job `depends_on`

Jobs can declare dependencies:

```yaml
depends_on: ["jobA", "jobB"]
```

Rules:

- a job is allowed to start only if **all** dependencies ended with status `SUCCESS`
- otherwise the job is marked `BLOCKED`
- a `BLOCKED` job does not execute its steps

This makes dependencies explicit and prevents accidental downstream work after an upstream failure.

---

## 3) Job `when` (Gating Expression)

Jobs can also be gated with a `when` expression:

- `when` is evaluated before any steps run
- if `when` evaluates to `false`, the job is marked `SKIPPED` (not failed)

The expression language is intentionally small and safe (AST allowlist). It typically supports:

- boolean operators: `and`, `or`, `not`
- comparisons: `== != > >= < <=`
- booleans: `true/false` (case-insensitive)
- access pattern:
  - `jobs.<job_id>.outputs.<key>`

Example:

```yaml
- id: transform
  depends_on: ["extract"]
  when: jobs.extract.outputs.row_count > 0
  steps:
    ...
```

If `when` is invalid (cannot parse / violates allowed AST), the runner raises an error and the flow run fails (this is a spec/runtime correctness problem, not a skip).

---

### Best practice: split probing into a dedicated job

For larger flows, isolate probing into a small job and gate downstream jobs from its outputs:

```yaml
jobs:
  - id: probe
    steps:
      - id: check
        type: check_items
        inputs:
          items: ""
        outputs:
          has_data: "{{ result.has_data }}"

  - id: process
    depends_on: [probe]
    when: jobs.probe.outputs.has_data == true
    steps:
      - id: extract
        type: db_extract
        inputs:
          resource: db_main
          sql: "SELECT 1 AS ok"
          output: out.tsv
```
It means, that job `process` will be run, only when job `probe` was SUCCESS and the condition is valid.

```yaml
jobs:
  - id: probe
    steps:
      - id: check
        type: check_items
        inputs:
          items: ""
        outputs:
          has_data: "{{ result.has_data }}"

  - id: process
    when: jobs.probe.outputs.has_data == true
    steps:
      - id: extract
        type: db_extract
        inputs:
          resource: db_main
          sql: "SELECT 1 AS ok"
          output: out.tsv
```
It means, that job `process` will be run, only when the condition is valid.

This pattern keeps the main processing job clean and avoids repeated “if empty then skip” logic.

---

## Skip vs Failure

AetherFlow distinguishes outcomes clearly:

### `SKIPPED` (Valid Outcome)
- “no data” outcome
- `when` evaluates to false
- step short-circuits via `on_no_data: skip_job`

### `FAILED` (Error)
- exception during step execution
- invalid spec or invalid `when` expression
- runtime resolution or validation error

---

## Anti-Pattern

Do **not** sprinkle “if empty, skip” checks across every step.

Instead:
- gate early (probe job or probe step)
- keep the rest of the job boring, deterministic, and resume-friendly

That’s the whole point of treating `SKIPPED` as first-class.
