# 92 — Demo Walkthrough

This walkthrough is built around the **actual demo content shipped in `demo`** and the core behavior implemented in `packages`.

What the shipped demo **does prove** (today):
1) `aetherflow` validates and runs a YAML flow end-to-end  
2) **Job gating** via `job.when` (downstream job is skipped when condition is false)  
3) **State-backed resume** (rerun with the same `--run-id` will skip completed steps/jobs)  
4) **Scheduler adapter** can trigger the flow on an interval (`aetherflow-scheduler run ...`)  

What the shipped demo **does NOT include as-is** (in `demo` snapshot):
- explicit `with_lock` usage (lock/overlap prevention)
- `external.process` usage (OS-level tools like dbt/spark)
  
Those two are covered in core (see builtins), but the demo folder currently doesn’t showcase them. This doc includes an **“Optional: add lock + external.process”** section to extend the demo in a clean, ops-friendly way.

---

## Files used in this walkthrough (from `demo`)

Single-flow demo folder:
- Flow: `demo/usecase-singleflow/flows/demo_flow.yaml`
- Profiles: `demo/usecase-singleflow/profiles.yaml`
- Secrets provider (optional): `demo/usecase-singleflow/secrets/set_envs.py`
- Scheduler config: `demo/usecase-singleflow/scheduler/scheduler.yaml`
- Demo README: `demo/usecase-singleflow/README.md`

Important paths configured inside the flow YAML:
- Workspace root (artifacts): `/tmp/demo_work`
- State DB (SQLite): `/tmp/demo_state/demo_flow.sqlite`

---

# 1) Install (choose one)

## A) Install from PyPI (end users)

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

python -m pip install -U pip
pip install "aetherflow-core[all]" aetherflow-scheduler
````

## B) Install from source (editable, for development)

From repo root:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e packages/aetherflow-core[all,dev]
pip install -e packages/aetherflow-scheduler[dev]
```

---

# 2) Validate the demo flow

Set the demo profiles file and (optionally) the secrets provider path:

```bash
export AETHERFLOW_PROFILES_FILE=demo/usecase-singleflow/profiles.yaml
export AETHERFLOW_SECRETS_PATH=demo/usecase-singleflow/secrets/set_envs.py  # optional
```

Provide the required DB URL for the demo (SQLAlchemy connector expects `DB_URL` in this demo profile):

```bash
export DB_URL="sqlite:///demo_state/demo.sqlite"
```

Run validate:

```bash
aetherflow validate demo/usecase-singleflow/flows/demo_flow.yaml
```

If you want machine-readable output:

```bash
aetherflow validate demo/usecase-singleflow/flows/demo_flow.yaml --json
```

---

# 3) Run the demo flow

```bash
aetherflow run demo/usecase-singleflow/flows/demo_flow.yaml
```

What happens (based on the YAML):

* Job `probe` runs `check_items` with `items: [demo]`

    * It publishes job outputs:

        * `has_data`
        * `count`
* Job `extract_only` depends on `probe` and is gated by:

```yaml
when: jobs.probe.outputs.has_data == true
```

If the gate passes, it runs `db_extract` and writes `data.tsv`.

---

# 4) Prove job gating + “skip downstream job” behavior

Open `demo/usecase-singleflow/flows/demo_flow.yaml` and change:

```yaml
items: [demo]
```

to:

```yaml
items: []
```

Then rerun:

```bash
aetherflow run demo/usecase-singleflow/flows/demo_flow.yaml
```

Expected behavior:

* `probe` still runs (it’s the gate producer job)
* `extract_only` is **SKIPPED** because the `when` expression evaluates to false

This proves:

* gating is **explicit**
* skip happens at the job boundary (clean + readable)

---

# 5) Prove state → resume (real resume, not vibes)

Core runner resume behavior (from `aetherflow.core.runner`):

* for each step, if state already contains `SUCCESS` or `SKIPPED`, the runner **skips the step** on rerun with the same run id

## 5.1 Force a failure

Temporarily break the SQL in `extract` step, e.g.:

```yaml
sql: "select * from does_not_exist"
```

Run with an explicit run-id:

```bash
aetherflow run demo/usecase-singleflow/flows/demo_flow.yaml --run-id demo_resume_001
```

It should fail in `extract_only.extract`.

## 5.2 Fix it and rerun the same run-id

Restore the original:

```yaml
sql: "select 1 as COL"
```

Rerun:

```bash
aetherflow run demo/usecase-singleflow/flows/demo_flow.yaml --run-id demo_resume_001
```

Expected result:

* previously completed steps/jobs are skipped
* only the failed step resumes

This proves:

* resume is **state-backed**
* resume is **deterministic**
* reruns don’t redo successful work

---

# 6) Inspect artifacts (workspace)

The flow sets:

* `workspace.root: "/tmp/demo_work"`
* `cleanup_policy: never`

So artifacts remain on disk.

Inspect:

```bash
ls -R /tmp/demo_work
```

Look for:

* per-flow / per-job / per-run directories
* the `data.tsv` artifact written by `db_extract`

(Exact subpaths can vary by runner layout, but it will always be under `/tmp/demo_work/...` because the flow pins it.)

---

# 7) Inspect the state DB (SQLite)

The flow sets:

* `state.backend: sqlite`
* `state.path: "/tmp/demo_state/demo_flow.sqlite"`

Inspect the DB:

```bash
ls -lh /tmp/demo_state/demo_flow.sqlite
```

If you have sqlite3 installed, you can peek:

```bash
sqlite3 /tmp/demo_state/demo_flow.sqlite ".tables"
sqlite3 /tmp/demo_state/demo_flow.sqlite "select * from step_state limit 20;"
```

(Actual table names depend on the state schema in `aetherflow.core.state`.)

---

# 8) Run the scheduler demo

The demo ships a scheduler config:

* `demo/usecase-singleflow/scheduler/scheduler.yaml`

Run it:

```bash
aetherflow-scheduler run demo/usecase-singleflow/scheduler/scheduler.yaml
```

The README says it schedules the demo flow every 5 minutes. This proves:

* scheduler can load config
* scheduler can trigger core runner repeatedly

---

# Optional: Add lock + `external.process` to the demo (recommended extension)

The demo snapshot does not include these two, but core supports them:

* `with_lock` builtin step (lock)
* `external.process` builtin step (OS-level command)

Below is a clean way to extend the demo flow.

## A) Add a lock to prevent overlap

Add a new job `locked_ops` that depends on `probe` and is gated (optional), then wrap a step with `with_lock`:

```yaml
- id: locked_ops
  depends_on: [probe]
  when: jobs.probe.outputs.has_data == true
  steps:
    - id: locked
      type: with_lock
      inputs:
        lock_key: "demo_flow_ops"
        ttl_seconds: 900
        step:
          id: do_work
          type: db_extract
          inputs:
            resource: db
            sql: "select 1 as COL"
            output: "locked.tsv"
            format: "tsv"
```

This proves:

* overlapping scheduler runs won’t stomp each other (single lock key)
* lock is explicit in YAML (no hidden global lock)

## B) Showcase `external.process` with env injection

Add a new job or step that runs a harmless OS command and shows env wiring:

```yaml
- id: os_tool
  depends_on: [probe]
  when: jobs.probe.outputs.has_data == true
  steps:
    - id: run_tool
      type: external.process
      inputs:
        command: ["bash", "-lc", "echo FLOW=$AETHERFLOW_FLOW_ID RUN=$AETHERFLOW_RUN_ID && echo DEMO_ENV=$DEMO_ENV"]
        cwd: "."
        env:
          DEMO_ENV: "hello_from_step_env"
        timeout_seconds: 60
        retry:
          max_attempts: 1
        log:
          stdout: capture
          stderr: capture
```

This proves:

* you can run OS-level tools in an ops-friendly way
* step-level env is deterministic and visible
* logs can be captured for debugging

---

# What this demo is “production-ish” about

Even though the core demo is small, it is designed to validate the important boring stuff:

* validate/run behavior doesn’t depend on dev-only tricks
* gating is explicit and readable
* resume is state-backed (not “just rerun everything”)
* artifacts are structured under a stable workspace root
* scheduler wiring works

If you want “real pipeline shape” (SFTP → unzip → transform → SMB → email, Excel reporting), use the other demo groups:

* `demo/usecase-multiflows-local/`
* `demo/usecase-multiflows-remote/`
