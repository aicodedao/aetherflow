# 10 — Flow YAML Guide 

Goal: write Flow YAML that is **safe, explicit, boring, and deterministic**.

This guide focuses on practical structure and step design.
For the formal schema, see `06-yaml-spec.md`.

Two step families are *special* and deserve extra attention:

- **Reporting steps** (`excel_fill_small`, `excel_fill_from_file`) — because payload size + templates can create production foot-guns.
  See: `21-reporting-guide.md`

- **`external.process`** — because it is the execution boundary to OS-level compute (spark/dbt/scripts) and requires strict idempotency/locking discipline.
  See: `22-external-process-step.md`

---

# 1) Execution Mental Model

AetherFlow is intentionally simple:

    Flow → Jobs → Steps

- A **Flow** defines workspace, state, resources, and execution plan.
- A **Job** runs steps sequentially (with optional `depends_on` and `when` gating).
- A **Step** performs one unit of work (connector operations or `external.process`).

Important properties:

- Jobs run sequentially.
- Steps run sequentially within a job.
- No implicit concurrency.
- No hidden retries.
- Resume behavior is state-driven.

If you need a dynamic DAG UI, use Airflow.
If you need a deterministic CLI runner, use AetherFlow.

---

# 2) Minimal but Realistic Example

    version: 1

    flow:
      id: demo
      workspace:
        root: /tmp/work
        cleanup_policy: on_success
      state:
        backend: sqlite
        path: /tmp/state/state.db

    resources:
      db_main:
        kind: db
        driver: postgres
        config:
          host: "{{ env.DB_HOST }}"
        decode:
          config:
            password: true

    jobs:
      - id: extract
        steps:
          - id: probe
            type: check_items
            inputs:
              items: ["a", "b"]
            outputs:
              row_count: "{{ result.count:0 }}"
            on_no_data: skip_job

      - id: transform
        depends_on: ["extract"]
        when: jobs.extract.outputs.row_count > 0
        steps:
          - id: run
            type: external.process
            inputs:
              cmd: ["bash", "-lc", "echo hello"]
              timeout_seconds: 60

What this demonstrates:

- probe-first gating (`check_items` + `on_no_data: skip_job`)
- promote metadata (`row_count`) as job output
- gate downstream job with `when`
- run OS-level work via `external.process`

---

# 3) Writing Jobs Correctly

## 3.1 Use `depends_on` for Correctness

Always declare dependencies when order matters:

    depends_on: ["extract"]

If the dependency does not end in SUCCESS:

- job becomes BLOCKED
- steps do not run

Do not rely on ordering alone for correctness.

---

## 3.2 Use `when` for Business Gating

Example:

    when: jobs.extract.outputs.row_count > 0

If false:

- job is marked SKIPPED
- steps do not execute

Expression language is intentionally restricted:

- and / or / not
- == != > >= < <=
- boolean literals
- jobs.<job_id>.outputs.<key>

Invalid syntax → runtime error (fail fast).

---

# 4) Step Design (General Contract)

Steps are where side effects happen. Design them like production operators would.

## 4.1 Step Structure

Minimal structure:

    - id: step_id
      type: step_type
      inputs: {}
      outputs: {}
      on_no_data: skip_job

Common fields:

- id (required, unique within job)
- type (required, resolved via registry)
- inputs (step-specific configuration; resolved via templating)
- outputs (optional promotion to job outputs)
- on_no_data (optional skip behavior)

Exact allowed inputs depend on step type.
See: `23-builtins-catalog.md`

---

## 4.2 Step Lifecycle

For each step:

1) Runner checks state store:
  - if already SUCCESS or SKIPPED → skip execution (resume)
2) Resolve inputs via templating
3) Execute step logic
4) Return StepResult(status, outputs)
5) Persist status in state
6) Promote outputs (if configured)

Statuses:
- SUCCESS
- SKIPPED

Failures raise exceptions → job FAILED.

---

## 4.3 Idempotency & Resume

A step must be:

- idempotent or resume-friendly
- atomic in its outputs
- explicit about side effects

Bad pattern:
- write partial file
- crash
- step gets marked SUCCESS anyway

Good pattern:
- write to temp
- move/rename atomically
- only then return SUCCESS

State-based resume will not protect you from non-idempotent logic.

See: `20-steps.md`

---

## 4.4 Outputs (Promote Metadata Only)

Example:

    outputs:
      row_count: "{{ result.count:0 }}"
      output_path: "{{ result.path }}"

Outputs:
- are rendered after step execution
- become job-level outputs
- are available to downstream jobs

Best practice:
- outputs should be small metadata only (counts, flags, paths)
- large data must go to artifact files

Reporting steps are the canonical example of this rule.
See: `21-reporting-guide.md`

---

## 4.5 Skip Behavior (`on_no_data`)

If a step returns SKIPPED and:

    on_no_data: skip_job

Then:
- remaining steps in the job are skipped
- job becomes SKIPPED

Use probe-first patterns:
- check existence/count/list
- skip early
- keep the rest boring

See: `04-skipping-and-gating.md`

---

# 5) Step Exception #1 — Reporting (Excel)

AetherFlow ships two reporting steps:

- `excel_fill_small`
- `excel_fill_from_file`

Why they are “special”:

- reporting templates can tempt you to pass large payloads through step outputs
- large in-memory payloads are fragile and slow
- production reporting should be file-based for big data

Two recommended patterns:

Pattern A — Small data fill:
- use `excel_fill_small`
- keep payload small (metadata-sized tables)

Pattern B — Large data fill:
- extract big data to an artifact file
- then use `excel_fill_from_file` to fill template from file

Full guide (canonical):
- `21-reporting-guide.md`

---

# 6) Step Exception #2 — `external.process` (Real Compute Boundary)

`external.process` is the primary orchestration step for OS-level compute:
- spark-submit
- dbt
- python scripts
- shell pipelines

Example:

    - id: run_job
      type: external.process
      inputs:
        cmd: ["spark-submit", "job.py"]
        timeout_seconds: 7200

Why it is “special”:

- it executes outside Python (process boundary)
- it can introduce non-idempotent side effects very easily
- it needs strict timeout + locking discipline

Best practices:

- always set timeouts
- make scripts idempotent (or resume-friendly)
- write outputs atomically (temp → rename)
- protect shared outputs/targets with locks
- prefer artifacts for large outputs (files), promote only metadata

Full spec + behavior:
- `22-external-process-step.md`

---

# 7) Locks for Side Effects

If a step writes to:

- shared file path
- shared table
- single-writer API

Wrap it using `with_lock`:

    - id: guarded
      type: with_lock
      inputs:
        lock_key: "export:orders"
        ttl_seconds: 1800
        step:
          id: do_export
          type: external.process
          inputs:
            cmd: ["bash", "-lc", "./export.sh"]

Locking is explicit by design.
See: `05-locking-guide.md`

---

# 8) Resources & Connectors in Steps

Steps should consume connectors via:

    ctx.connectors["resource_name"]

Resources are:
- resolved via strict templating
- overlayed via profiles
- decoded via secrets hook (explicit decode map)
- instantiated deterministically via registry

Never build connectors manually inside steps.

See:
- `09-profiles-and-resources.md`
- `19-connectors.md`

---

# 9) Environment Rules

At runtime:
- runner builds immutable `ctx.env`
- steps should not read from `os.environ`
- use templating: {{ env.VAR }}

Bundle mode may override:
- profiles file
- plugin paths
- env files

See:
- `08-manifest-and-bundles.md`
- `11-envs.md`

---

# 10) Production Safety Checklist

Before shipping a flow:

- explicit `depends_on` between jobs
- explicit `when` for business gating
- probe-first pattern for no-data
- locks around shared side effects
- timeouts for external processes
- outputs are metadata only
- validate before run:

  aetherflow validate flow.yaml

---

# 11) Philosophy

AetherFlow flows should be:

- deterministic
- explicit
- sequential
- reviewable
- free of hidden behavior

Keep jobs boring.
Make side effects explicit.
Validate early.
Fail fast.

That is the design.
