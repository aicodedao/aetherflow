# 91 — Use Cases & Extension Notes

Goal of this page:
- point you to **production-ish demos** that stay aligned with the **core YAML schema**
- explain **what each demo proves**
- show **where plugins live** and how they integrate with core

Sources reviewed:
- Core runtime + schema: `packages/aetherflow-core/src/aetherflow/core/...`
- Demo bundles + plugins: `demo`

If you’re new, read these first:
- `10-quickstart.md`
- `11-flow-yaml-guide.md`

If you want a full guided walkthrough, see:
- `92-demo-walkthrough.md` (referenced by docs set; not included in the zip snapshots here)

---

# What’s in `demo`

`demo` contains **three demo groups**:

1) `demo/usecase-multiflows-local/`
   - “infra-free” runnable demos using local/mock connectors + dummy mail

2) `demo/usecase-multiflows-remote/`
   - same use cases but wired for “real-ish” infra (SFTP, SMB, Exasol)

3) `demo/usecase-singleflow/`
   - minimal smoke demonstrating core runner behaviors (job gating, check_items, scheduler config)

---

# Use Case 1 — SFTP → unzip → transform → zip → SMB → email

## Flow files

### Local (no infra)
- Flow:
  - `demo/usecase-multiflows-local/uc1/flows/demo_local.yaml`
- Bundle manifest:
  - `demo/usecase-multiflows-local/uc1/manifest_local.yaml`

### Remote (real-ish infra wiring)
- Flow:
  - `demo/usecase-multiflows-remote/uc1/flows/main.yaml`
- Bundle manifest:
  - `demo/usecase-multiflows-remote/uc1/manifest_smb.yaml`

## What it proves (in this repo snapshot)

### End-to-end file pipeline shape
The UC1 flow demonstrates a realistic “file movement” workflow:

- SFTP list
- SFTP download (batch)
- unzip
- transform CSV (custom step)
- zip
- SMB upload (batch)
- send notification email

### Step graph (from YAML)
In the demo snapshot, UC1 step types are:

- `sftp_list_files`
- `sftp_download_files`
- `unzip` *(builtin)*
- `local_transform_csv`
- `zip` *(builtin)*
- `smb_upload_files`
- `mail_send` *(builtin)*

Local-only adds a prep step:
- `demo_prepare_inbox`

## Where the “non-builtin” logic lives (plugins)

UC1 is intentionally a mix of:
- **core builtins** (`zip`, `unzip`, `mail_send`)
- **demo plugins** for infra-specific IO

UC1 plugin layout:

- Plugins package root:
  - `demo/usecase-multiflows-*/uc1/plugins/`

### Plugin connectors (examples)
- `plugins/connectors/sftp_local.py`
- `plugins/connectors/sftp_moveit.py`
- `plugins/connectors/smb_local.py`
- `plugins/connectors/smb_pysmb.py`
- `plugins/connectors/mail_dummy.py`

### Plugin steps (examples)
- `plugins/steps/sftp_steps.py` *(defines `sftp_list_files`, `sftp_download_files`)*
- `plugins/steps/smb_upload.py` *(defines `smb_upload_files`)*
- `plugins/steps/local_transform.py` *(defines `local_transform_csv`)*
- `plugins/steps/demo_prepare_inbox.py` *(local demo data setup)*

What this proves:
- the **plugin contract** works end-to-end
- your org can keep “ops adapters” (SFTP/SMB specifics) outside core
- your flows remain readable while connectors/steps remain swappable by profile

---

# Use Case 2 — Exasol → (stream) CSV → Excel (2 targets) → SMB → email

## Flow files

### Local (no DB)
- Flow:
  - `demo/usecase-multiflows-local/uc2/flows/demo_local.yaml`
- Bundle manifest:
  - `demo/usecase-multiflows-local/uc2/manifest_local.yaml`

### Remote (Exasol streaming)
- Flow:
  - `demo/usecase-multiflows-remote/uc2/flows/main.yaml`
- Bundle manifest:
  - `demo/usecase-multiflows-remote/uc2/manifest_smb.yaml`

## What it proves

### Big-data safe extraction pattern
Remote UC2 uses **streaming extracts** twice (two datasets):

- `db_extract_stream`
- `db_extract_stream`

This demonstrates the “file-first” pipeline design:
- DB → stream → artifact file
- Excel reads the artifact file
- avoids passing large payload through templating / step outputs

### Excel reporting pattern (file → template fill)
Both local and remote UC2 use:
- `excel_fill_from_file` *(builtin)*

Additionally, UC2 uses a template validation step that is **demo plugin**, not core builtin:
- `excel_validate_template` *(plugin step)*

Local UC2 uses plugin steps to generate CSVs:
- `demo_write_csv` *(appears twice in YAML; implemented by plugin)*

### Step graph (from YAML)
Remote UC2 types (in demo snapshot):
- `db_extract_stream` (x2) *(builtin)*
- `excel_validate_template` *(plugin)*
- `excel_fill_from_file` *(builtin)*
- `smb_upload_files` *(plugin)*
- `mail_send` *(builtin)*

Local UC2 types:
- `demo_write_csv` (x2) *(plugin)*
- `excel_validate_template` *(plugin)*
- `excel_fill_from_file` *(builtin)*
- `smb_upload_files` *(plugin)*
- `mail_send` *(builtin)*

## Where UC2 plugins live
- `demo/usecase-multiflows-*/uc2/plugins/`

Notable plugin steps:
- `plugins/steps/demo_generate_csv.py`
- `plugins/steps/demo_prepare_excel_template.py`
- `plugins/steps/excel_validate_template.py`
- `plugins/steps/smb_upload.py`

What this proves:
- you can keep Excel templating logic minimal in core
- your org can add stricter “template contract” validation as a plugin
- the recommended reporting pattern scales: **extract → file → fill**

---

# Minimal Use Case — Singleflow smoke (job gating + scheduler config)

## Files
- Flow:
  - `demo/usecase-singleflow/flows/demo_flow.yaml`
- Scheduler config:
  - `demo/usecase-singleflow/scheduler/scheduler.yaml`
- Readme:
  - `demo/usecase-singleflow/README.md`

## What it proves

### Job gating via `job.when`
The flow has two jobs:
- `probe`
- `extract_only`

`extract_only` is gated by:

- `when: jobs.probe.outputs.has_data == true`

This proves:
- job outputs can feed job gating
- the runner evaluates gating before executing downstream jobs

### Step-level skip semantics (`on_no_data: skip_job`) — described, not enabled by default
This snapshot does **not** include `on_no_data` in the YAML by default.
Instead, the flow comments explain how to try it:
- move the “gate step” into the job and set `on_no_data: skip_job`

This proves:
- the recommended pattern is to keep the flow deterministic
- skip behavior is explicit and opt-in (not “magic”)

---

# Bundle / plugins wiring (what the demo shows)

The multi-flow demos are designed to be run through bundle manifests.

Example (local UC1 manifest):
- `demo/usecase-multiflows-local/uc1/manifest_local.yaml`

Key fields shown in demo manifests:
- `mode: internal_fast`
- `layout.plugins_dir: plugins`
- `layout.flows_dir: flows`
- `layout.profiles_file: profiles.yaml`
- `entry_flow: flows/main.yaml` *(remote manifests)*
- local demo uses `flows/demo_local.yaml` as the runnable file

What this proves:
- “internal_fast” mode can map a `plugins_dir` directly into plugin paths (dev convenience)
- you can keep flows/profiles/plugins together as a self-contained bundle

---

# Extension Notes (How to add your own production logic)

## Add a new connector (recommended pattern)
- Implement a connector class with a small, stable public surface (methods steps will call).
- Register it via **public API only**:

```python
from aetherflow.core.api import register_connector

@register_connector("mykind:mydriver")
class MyConnector:
    ...
````

Best practices:

* keep dependencies optional (lazy import inside connector)
* keep config schema explicit and validated
* implement `close()` if you manage network sessions

## Add a new step (recommended pattern)

* Implement a Step and register it via **public API only**:

```python
from aetherflow.core.api import register_step

@register_step("my.custom_step")
class MyCustomStep:
    ...
```

Best practices:

* make outputs atomic and resume-friendly
* write large results to artifacts instead of step outputs
* avoid pandas-in-RAM patterns for bulk data (prefer streaming)

## About “lock to avoid overlap”

AetherFlow supports this via the builtin `with_lock` step.
In the current `demo`, **none of the shipped demo flows use `with_lock` explicitly**.
If your tool cannot tolerate concurrent runs, wrap it:

* `with_lock` around `external.process` (dbt, spark-submit, etc.)
* or around any IO-heavy pipeline

(See `24-responsibility-model.md` for ownership: core provides the lock primitive; you decide where to apply it.)

---

# Quick “what should I run first?”

* Want to see plugins + real-ish pipeline shape?
    * Start with UC1 local:
        * `demo/usecase-multiflows-local/uc1/flows/demo_local.yaml`

* Want to see streaming extract → Excel reporting?
    * Start with UC2 remote (conceptually) or UC2 local (infra-free):
        * local: `demo/usecase-multiflows-local/uc2/flows/demo_local.yaml`
        * remote: `demo/usecase-multiflows-remote/uc2/flows/main.yaml`

* Want minimal runner semantics (job gating)?
    * `demo/usecase-singleflow/flows/demo_flow.yaml`
