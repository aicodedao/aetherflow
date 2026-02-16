# 00 — Overview

AetherFlow is a **YAML-first workflow engine** for ops-grade ETL/ELT/Automation workloads.

It is designed to run safely and predictably on:
- **cron**
- **containers**
- **schedulers** (including `aetherflow-scheduler`)

AetherFlow’s core promise is boring reliability:
- **deterministic runs**: same inputs → same execution plan → same state transitions
- **reproducible + blame-proof**: you can explain *what ran*, *with which env*, *which resources*, and *which bundle*

---

## What AetherFlow is

AetherFlow is a runner that executes a **Flow YAML** using a simple execution model:

- **Flow → Job → Step**

You describe:
- jobs and their dependencies
- steps and their inputs
- resources/connectors (DB, SFTP, SMTP, HTTP, archives)
- profiles and environment mappings

Then the runner:
- validates the spec
- resolves templates (strict contract)
- executes steps deterministically
- records job/step state into a state store

---

## State-backed execution (why it matters)

AetherFlow ships with a state store (SQLite backend in this repo snapshot) to support:

- **resume**:
  - rerun with the same `run_id` to skip steps already `SUCCESS` or `SKIPPED`
- **status tracking**:
  - job/step status recorded explicitly (`RUNNING`, `SUCCESS`, `FAILED`, `SKIPPED`)
- **locks**:
  - TTL-based distributed mutex to prevent overlapping runs (`with_lock`)

This means:
- failures are debuggable
- partial runs are recoverable
- “overlap” is a conscious decision (explicit lock usage)

---

## What AetherFlow is NOT

AetherFlow is intentionally minimal. It does not try to be a platform.

It is **not**:

- **Apache Airflow**
- a UI-first orchestrator
- a webserver or scheduler UI
- a DAG authoring UI
- a compute engine
  - it does not provision clusters
  - it does not autoscale worker fleets
  - it does not manage distributed compute resources

AetherFlow runs *on top of* whatever compute you already have:
- a container runtime
- a VM
- Kubernetes CronJobs
- system cron
- a scheduler process

---

## What AetherFlow refuses to do

AetherFlow does not decide business semantics for you.

Examples of things the user must define explicitly:
- what “success” means (marker files, validations)
- what “no data” means (skip vs fail)
- idempotency and side effects (safe reruns)
- retention policy of state and artifacts
- security posture for secrets and plugins

AetherFlow provides guardrails and primitives, but it does not guess.

---

## Philosophy (project style)

### YAML-first
The spec is data:
- easy to review
- easy to diff
- easy to audit
- stable to generate from tooling

### Boring deterministic runner
- minimal magic
- explicit state transitions
- predictable failure behavior
- strict templating contract

### Config-over-code
You change behavior via:
- profiles
- resources
- settings
- bundles

Not by shipping custom code inside every flow.

(When you do need custom logic, use plugins — and treat them as real code deployments.)

### Single Resolver Architecture
AetherFlow uses a single strict template resolver across:
- resources (env-only)
- step inputs/outputs (env + steps + job outputs + run metadata)

Templating is deliberately small:
- only `{{PATH}}` and `{{PATH:DEFAULT}}`
- everything else fails fast

This keeps runs deterministic and reviewable.

---

## TL;DR

AetherFlow is a **YAML-first, ops-grade workflow engine** focused on:
- safe execution on cron/containers/schedulers
- deterministic, reproducible runs
- state-backed resume and locking

It is not Airflow, not a UI platform, and not a compute engine.

