# 24 — Responsibility Model (Backend Format)

AetherFlow is intentionally “not magical”.
It does not hide decisions — it forces them to be explicit so runs stay boring, reviewable, and reproducible.

This page defines the responsibility boundaries between:
- **AetherFlow core** (the framework)
- **the user / platform team** (your org)
- **deployment profiles** (`internal_fast` vs `enterprise`)

---

## Design principle: explicit decisions > implicit convenience

AetherFlow avoids:
- silent retries with unknown policies
- hidden defaults that change behavior across environments
- “smart” auto-detection that makes runs non-deterministic

Instead it pushes you to define:
- what “success” means
- what is safe to rerun
- what sources of code/plugins are trusted
- what state data must be retained vs expired

---

# Who owns what?

## AetherFlow core owns

### Deterministic runner
Core guarantees:
- step execution ordering is deterministic
- retries happen only when configured
- step outputs are serialized the same way across runs
- failures surface as explicit errors with context

### Strict templating contract
Core guarantees:
- templating is string-based and explicit
- step inputs/outputs boundaries are clear
- payload size limits are enforced where relevant (ex: reporting thresholds)
- no “magic coercion” across steps without opt-in

### State-backed resume + lock
Core guarantees:
- resume semantics are state-backed (not “best effort”)
- lock acquisition is explicit (`with_lock`)
- lock TTL and failure behavior are explicit

### Minimal observability hooks
Core provides:
- structured step lifecycle events
- step-level logs and summarized outputs
- stable identifiers (flow_id, run_id, step_id)
- integration points for external logging/metrics/tracing

Core does **not** force an observability stack.

---

## User owns

### Business logic
You define:
- what “success” means (markers, row counts, validations)
- what “no data” means (is it expected? is it a failure?)
- what thresholds matter (report row limits, extract sizes)

Core will not guess.

### Idempotency
You own rerun safety:
- external systems side effects
- whether rerunning creates duplicates
- how to avoid partial writes

Recommended tools:
- idempotency markers (marker files / success flags)
- atomic output dirs
- `with_lock` for “no overlap allowed” workloads

### Retention policies of the state DB
You own:
- retention windows for run history
- cleanup strategy for old artifacts and logs
- compliance retention requirements

Core stores what it needs to resume and explain runs.
You decide how long that data lives.

### Security posture of secrets hooks + plugins
You own:
- how secrets are injected (vault, env, KMS, custom hook)
- which plugins are allowed to execute
- how plugin code is reviewed and deployed

Core provides plugin interfaces and enforcement points.
You decide trust boundaries.

---

# Deployment Profiles

AetherFlow supports two operational profiles.
They trade off speed/convenience vs strict trust boundaries.

---

## `internal_fast` profile

Goal: developer velocity.

Characteristics:
- allows bundling a `plugins_dir` directly into plugin lookup paths
- supports ambient plugin paths (dev-friendly)
- prioritizes “works locally” ergonomics

Implications:
- higher risk if the environment is not locked down
- more freedom to load plugins from filesystem paths

Use when:
- internal team workflows
- non-prod / trusted execution environments
- you want rapid iteration without packaging overhead

---

## `enterprise` profile

Goal: trusted code only (auditable + controlled execution).

Characteristics:
- denies ambient plugin paths
- only loads plugin paths from `manifest.paths.plugins`
- archive drivers are allowlisted
- plugin loading is strict and predictable

Implications:
- higher setup overhead (you must package/register plugins)
- reduced blast radius from filesystem / path injection attacks
- clearer audit boundary for “what code ran”

Use when:
- production environments
- regulated / compliance-driven deployments
- multi-tenant runners or shared infra

---

# Practical guidance (how to not get burned)

## Make success explicit
- External tools: marker files (`_SUCCESS`, exported file exists, dbt artifacts)
- Extracts: row_count rules and schema validation
- Reports: enforce thresholds (`rows_threshold`) and fail fast

## Make reruns safe
- Prefer atomic output dirs for directory outputs
- Prefer marker strategy for long-running external steps
- Use `with_lock` when tools can’t tolerate overlap

## Treat plugins as code deployments
- Version, review, and package plugins like application code
- In enterprise: do not rely on filesystem paths
- Keep a manifest of exactly what plugins are allowed

---

# Summary

AetherFlow core provides:
- deterministic execution
- explicit templating and chaining
- state-backed resume + lock
- minimal hooks for observability

You provide:
- business semantics
- idempotency rules
- state retention policy
- security posture for secrets + plugins

Profiles:
- `internal_fast` = speed + convenience
- `enterprise` = trusted code only + allowlists
