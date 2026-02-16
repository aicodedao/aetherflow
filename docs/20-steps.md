```markdown
# 20 — Steps

Sources:
- `aetherflow.core.steps.base`
- registry: `aetherflow.core.registry.steps`
- built-ins: `aetherflow.core.builtins.steps`
- runner integration: `aetherflow.core.runner` (resume + state checks)
- skipping/gating semantics: `aetherflow.core.validation` + job runner logic
- locking: `aetherflow.core.state` + built-in step `with_lock`

This document is a step author guide focused on ops-grade semantics:
- idempotency and resumability
- atomic outputs
- explicit failure vs skip behavior
- no global/process-wide mutation
- connectors as primitives
- correct skip and lock patterns

---

## 1) What a Step Is

A step is the smallest executable unit in a job.

A job runs steps sequentially.
A flow runs jobs sequentially (subject to gating).

A step:
- receives a run context (`ctx`) and resolved `inputs`
- performs a single unit of work
- returns a `StepResult` with:
  - status
  - outputs (metadata)

A step must be safe to re-run because state-based resume can skip completed steps, but crashes and retries still happen.

---

## 2) Step Execution Contract (What the Runner Expects)

At runtime, the runner:

1) checks state store for the step status (run_id + job_id + step_id)
2) if status is SUCCESS or SKIPPED, it does not re-run the step (resume behavior)
3) resolves step inputs via the resolver pipeline
4) executes step logic
5) records step status in state
6) promotes outputs to job outputs (if configured)

Implications for step authors:

- your step may not run again after being marked SUCCESS/SKIPPED
- therefore, SUCCESS must only be returned after side effects are complete and durable
- partial writes are not acceptable

See:
- 03-execution-model.md
- 17-state.md

---

## 3) Ops Semantics: The Four Non-Negotiables

### 3.1 Idempotent / Resume-Friendly

A production-grade step must support at least one of:

- idempotency: running twice produces the same final state
- resumability: running again detects prior completion and does nothing harmful

Examples of good idempotency patterns:

- write to partitioned destination (date partition, run_id partition)
- upsert with stable keys
- “create if not exists” semantics
- check-and-skip based on durable marker file or state in target system

Bad patterns:

- append-only writes to a shared table without a unique key
- overwriting a fixed path without coordination
- “fire-and-forget” side effects that cannot be detected

---

### 3.2 Atomic Outputs

If your step writes an artifact (file, report, export), use atomic write patterns.

Recommended file pattern:

- write to temp path under the job workspace
- fsync if needed (environment-specific)
- rename/move to final path (atomic on same filesystem)
- only then return SUCCESS

Recommended DB pattern:

- write to staging table / temp table
- validate counts/checksums
- swap/commit
- only then return SUCCESS

Never return SUCCESS after a partial output.

---

### 3.3 No Process-Wide Mutation

Steps must not mutate global process state. That includes:

- setting `os.environ`
- changing working directory globally
- monkeypatching modules
- modifying global singletons shared across runs

Why:
- the runner uses an immutable env snapshot (`ctx.env`)
- multiple runs may share a process (scheduler / tests / embedded usage)
- global mutation causes nondeterministic behavior

Use:
- `ctx.env` for configuration
- explicit inputs for step config
- connectors from `ctx.connectors` for external systems

See:
- 11-envs.md
- 15-concurrency.md

---

### 3.4 Explicit Failure Modes

A step has two valid outcomes:

- SUCCESS: work completed as intended
- SKIPPED: no work was needed / “no data” is a valid outcome

Anything else should be a failure via exception.

Rules:

- return SKIPPED for “no data” or “condition not met” paths
- raise exception for real errors:
  - invalid inputs
  - connection failure
  - corrupted data
  - unexpected runtime error

Do not encode errors as “SKIPPED”.
Do not swallow exceptions and pretend SUCCESS.

---

## 4) Connectors as Primitives (How Steps Should Do IO)

Steps should never create raw drivers directly.

Instead:
- define resources in YAML
- let runner resolve and build connectors
- use `ctx.connectors["name"]` inside the step

This guarantees:
- consistent secrets decoding
- consistent config/options merge
- consistent caching policy
- deterministic resolution via the same pipeline

See:
- 19-connectors.md
- 09-profiles-and-resources.md
- 12-secrets.md

---

## 5) Skip Patterns (Correct “No Data” Semantics)

### 5.1 Step SKIPPED is First-Class

AetherFlow treats SKIPPED as a valid status, not a failure.

Use cases:
- no new rows
- empty file list
- upstream condition not met

Return SKIPPED with outputs that explain why:

- count
- reason
- has_data flag

Example outputs (recommended):

- has_data: false
- count: 0
- reason: "no new rows"

### 5.2 skip_job short-circuit

If the YAML step sets:

on_no_data: skip_job

And the step returns SKIPPED:

- the rest of the job is skipped
- job status becomes SKIPPED

This is the canonical “probe-first” optimization.

See:
- 04-skipping-and-gating.md
- 10-flow-yaml-guide.md

---

## 6) Lock Patterns (Correct Side-Effect Coordination)

A step that writes to a shared target must be protected if concurrent runs can collide.

Examples requiring locks:
- writing to a fixed output path
- loading into a shared non-partitioned table
- calling a single-writer API
- sending “exactly-once” notifications

Preferred pattern:
- use built-in `with_lock` step to wrap the critical section

Lock keys should describe the shared side effect:

- load:FACT_SALES
- export:orders
- upload:dropzone:/incoming/orders

Avoid lock keys tied to run_id (those protect nothing).

See:
- 05-locking-guide.md
- 17-state.md

---

## 7) Step Public API and Registration

Steps should rely on the public API only.

Imports:

    from aetherflow.core.api import Step, StepResult, STEP_SUCCESS, STEP_SKIPPED

Registration:

    from aetherflow.core.api import register_step

Minimal skeleton:

    from aetherflow.core.api import register_step, Step, StepResult, STEP_SUCCESS, STEP_SKIPPED

    @register_step("my_step")
    class MyStep(Step):
        def run(self, ctx, inputs):
            # read from ctx.env, use ctx.connectors, write artifacts atomically
            # return StepResult(status=..., outputs={...})
            return StepResult(status=STEP_SUCCESS, outputs={"ok": True})

Plugins must import from `aetherflow.core.api` only.

See:
- 18-plugins.md
- 25-public-api-and-semver.md

---

## 8) MUST-HAVE vs NICE-TO-HAVE (Step Author Checklist)

### MUST-HAVE

- idempotent or resume-friendly behavior
- atomic outputs
- explicit SKIPPED vs exception failure
- no global/process mutation
- uses connectors (ctx.connectors) instead of raw drivers
- emits small metadata outputs only

### NICE-TO-HAVE

- meaningful structured outputs (count, paths, flags)
- deterministic file naming
- consistent artifact layout under job workspace
- internal concurrency only when safe and documented

---

## 9) Related Docs

- 03-execution-model.md — lifecycle + status model
- 04-skipping-and-gating.md — skip semantics and gating patterns
- 05-locking-guide.md — distributed mutex and `with_lock`
- 09-profiles-and-resources.md — profiles + resources build pipeline
- 19-connectors.md — connectors lifecycle, caching, extending
- 10-flow-yaml-guide.md — practical YAML authoring patterns
- 25-public-api-and-semver.md — stability rules for plugin authors
```
