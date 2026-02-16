# 93 — Flow in 15 Minutes
No philosophy. Ship something first.

This guide uses **only what ships in this repo**:
- `aetherflow` (meta) → installs `aetherflow-core` + `aetherflow-scheduler`
- Builtin step: `external.process`
- Optional scheduler: `aetherflow-scheduler`

---

## 1) Install

If you want the “one command” install:

```bash
pip install aetherflow
````

If you only want core (no scheduler):

```bash
pip install "aetherflow-core[all]"
```

---

## 2) Create `flow.yaml`

Save this as `flow.yaml`:

```yaml
version: 1

flow:
  id: fifteen
  workspace:
    root: /tmp/work
    cleanup_policy: on_success
  state:
    backend: sqlite
    path: /tmp/state/state.db

jobs:
  - id: main
    steps:
      - id: hello
        type: external.process
        inputs:
          command: ["bash", "-lc", "echo 'hello from aetherflow'"]
          timeout_seconds: 30
          log:
            stdout: inherit
            stderr: inherit
```

What this flow does:

* creates a workspace under `/tmp/work`
* stores state in SQLite at `/tmp/state/state.db`
* runs a single OS-level command via `external.process`

---

## 3) Run it

```bash
aetherflow run flow.yaml
```

You should see the command output in your terminal.

---

## 4) Inspect artifacts + state (quick sanity)

Artifacts:

```bash
ls -R /tmp/work
```

State DB:

```bash
ls -lh /tmp/state/state.db
```

(If you have sqlite3 installed:)

```bash
sqlite3 /tmp/state/state.db ".tables"
```

---

## 5) Schedule it (optional)

Create `scheduler.yaml`:

```yaml
timezone: Europe/Berlin
items:
  - id: fifteen-min
    cron: "*/5 * * * *"
    flow_yaml: flow.yaml
```

Run scheduler:

```bash
aetherflow-scheduler run scheduler.yaml
```

This will trigger the flow every 5 minutes.

Stop it with `Ctrl+C`.

---

## 6) Next steps (pick one)

* Want “real pipeline shape”? Jump to:
    * `91-use-cases-and-extension-notes.md`

* Want a guided proof of validate/run/state/resume?
    * `92-demo-walkthrough.md`

* Want Excel reporting patterns?
    * `21-reporting-guide.md`
