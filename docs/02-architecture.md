# 02 — Architecture

AetherFlow makes deliberately “boring but durable” design choices so workflows can run safely in production.

The goal is not to be flashy.
The goal is to be predictable, reviewable, and operationally simple.

---

## 1) YAML-First

In AetherFlow, a flow is **data**.

You describe behavior in YAML:
- flow structure
- jobs and steps
- resources
- profiles
- environment configuration

This has important consequences:

- A pipeline change = change in YAML + profiles/resources
- Changes are diffable and reviewable
- You do not need to ship custom runtime code to modify behavior
- CI/CD can treat flows like configuration artifacts

The engine focuses on executing a declarative spec — not embedding user business logic inside the runner.

Spec definitions live in `aetherflow.core.specs`  
Validation rules live in `aetherflow.core.validation`

The YAML contract is documented in:

→ **06-yaml-spec.md**

---

## 2) Single Resolver Architecture (Core Design Principle)

AetherFlow uses a **single resolution pipeline** for all templated values.

This is one of the defining architectural decisions of the project.

The same resolver pipeline is used for:

- Resource configuration and options
- Step inputs
- Step outputs (including promotion to job outputs)
- Manifest/bundle-derived paths
- Profile-expanded configuration

There is no separate templating logic per subsystem.

All resolution flows through:

`aetherflow.core.resolution`

This guarantees:

- Consistent variable precedence
- Deterministic expansion
- Strict-mode enforcement
- Predictable failure behavior

Templating strictness and error taxonomy are defined in:

→ **99-strict-templating.md**

### Concurrency Note

The core runner does **not** spawn threads to execute flows.

If you want concurrency:

- Run multiple processes
- Use containers
- Use the scheduler
- Use Kubernetes Jobs/CronJobs

Steps may use threads or async internally when it makes sense (for example batch uploads), but that is a step implementation detail — not a responsibility of the core runner.

---

## 3) Execution Boundary

Execution is structured and explicit:

- Flow → multiple Jobs
- Job → multiple Steps (sequential)
- Step → may use connectors or call external processes

Core execution is:

- Sequential per job
- Deterministic
- Resume-aware (via state backend)
- Lock-aware (if configured)

The runner logic lives under:

- `aetherflow.core.runner`
- `aetherflow.core.runtime.*`
- `aetherflow.core.state`

AetherFlow does **not** try to scale compute itself.

Instead:

- Steps may call Spark, dbt, Python scripts, etc.
- The built-in `external.process` step executes OS-level commands
- The scheduler is responsible only for triggering runs

See:

→ **03-execution-model.md**  
→ **22-external-process-step.md**

---

## 4) Why No UI / Webserver?

AetherFlow is intentionally **CLI-first**.

It is designed to run inside environments you already operate:

- cron / systemd timers
- containers
- Kubernetes Jobs / CronJobs
- a lightweight scheduler service

Not shipping a webserver means:

- Reduced attack surface
- No UI database
- No auth/RBAC layer to maintain
- No migrations
- No operational overhead from web infrastructure

Logs and state are the source of truth.

They can be integrated into your existing observability stack without forcing you into a specific UI model.

This keeps the core small and predictable.

---

## 5) Config-Over-Code

Environment-dependent behavior is controlled via configuration, not embedded runtime code.

What typically changes between environments:

- Environment snapshot and env files
- Profiles mapping environment → resource configuration
- Resource definitions → connector instances
- Plugin paths
- Strict mode settings

During execution:

- The runner snapshots environment state
- It does **not mutate `os.environ`**
- Resolution operates on the snapshot
- Connectors are built from resolved resource definitions

This ensures:

- Reproducibility
- Isolation between runs
- “Blame-proof” configuration behavior

See:

→ **09-profiles-and-resources.md**  
→ **11-envs.md**  
→ **14-settings.md**

---

## 6) Resources → Connectors → Steps

AetherFlow cleanly separates responsibilities:

1. **Resources**
    - Resolved configuration
    - Decoded/expanded secrets
    - Environment/profile-derived values

2. **Connectors**
    - Thin wrappers around drivers/transports (DB, HTTP, SFTP, SMTP, etc.)
    - Created from resources
    - Exposed via `ctx.connectors`
    - No global state

3. **Steps**
    - Orchestration layer
    - Use connectors as primitives
    - Implement idempotency and resume semantics
    - Produce atomic outputs
    - Declare skip/lock behavior explicitly

This separation makes it possible to:

- Extend via plugins
- Add connectors without modifying core
- Add steps without patching internal modules
- Maintain a stable public API surface (`aetherflow.core.api`)

See:

→ **18-plugins.md**  
→ **19-connectors.md**  
→ **20-steps.md**

---

## 7) Design Summary

AetherFlow chooses:

- YAML-first configuration
- A single resolution pipeline
- Sequential deterministic execution
- Explicit state + locking
- No UI/webserver
- Config over embedded code
- Clear boundaries between resources, connectors, and steps

The result is a workflow engine optimized for:

- Production-grade ETL
- Safe cron/container execution
- Deterministic behavior
- Minimal operational surface
