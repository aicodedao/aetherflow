# 05 — Locking Guide (Distributed Mutex via State)

AetherFlow implements locking as a **distributed mutex stored in the flow’s state backend**.

The contract is intentionally boring and explicit:

- There is **no implicit “job lock” field** in the YAML schema.
- There is no hidden magic.
- If you need exclusivity, you must declare it explicitly.

Relevant modules:

- `aetherflow.core.state`
- Built-in step: `with_lock`

Current state backend:

- **SQLite** (single file database)
- Locks stored in a `locks` table

Locking is built on top of the same state backend that powers resume and crash recovery.

---

# 1. Locking Philosophy

Locking is **explicit by design**.

AetherFlow does not automatically:

- Lock flows
- Lock jobs
- Prevent overlapping runs

If exclusivity matters, you must wrap the critical section in a lock.

This keeps behavior predictable and avoids surprising hidden coordination.

---

# 2. The Built-in `with_lock` Step

The standard way to acquire a lock is the built-in `with_lock` step.

It:

1. Acquires a lock using a key and TTL
2. Executes an inner step
3. Releases the lock

If the lock cannot be acquired, the step fails fast.

This allows:

- The scheduler to retry later
- The flow to surface overlap explicitly

Example:

```yaml
jobs:
  - id: export
    steps:
      - id: export_single_writer
        type: with_lock
        inputs:
          lock_key: "export:orders"
          ttl_seconds: 1800
          step:
            id: do_export
            type: external.process
            inputs:
              cmd: ["bash", "-lc", "./export_orders.sh"]
```

In this example:

- Only one run can execute `do_export` at a time
- The lock is released when the inner step completes
- If acquisition fails, the step fails immediately

---

# 3. When You Need a Lock

Use a lock only when overlapping runs can cause damage.

Typical scenarios:

- Writing to a fixed output path
- Loading into a shared/non-partitioned table
- Calling a single-writer API
- Running non-idempotent external processes
- Preventing overlap between frequent cron runs

Do **not** lock:

- Read-only steps
- Pure transformations with isolated outputs
- “Just in case”

Lock only when there is a real shared side-effect.

---

# 4. Lock Implementation Details

Locks are stored in the state backend.

Example schema (conceptually):

```
locks(
  key TEXT PRIMARY KEY,
  owner TEXT,
  expires_at INTEGER
)
```

Operations are implemented in:

```
StateStore.try_acquire_lock(...)
```

Mechanism:

- **Acquire**
    - Insert or replace row if:
        - Lock is expired
        - Or owned by same owner (depending on implementation semantics)
- **TTL**
    - `expires_at` stored as epoch seconds
- **Release**
    - Delete row if owner matches

Ownership is tied to the current run.

---

# 5. Lock Keys

Lock keys should describe the shared side-effect, not the run.

Good examples:

- `export:mandant:AV`
- `load:table:FACT_SALES`
- `upload:dropzone:/incoming/orders`

Bad example:

- `lock:<run_id>`

Keys tied to `run_id` do not protect shared resources.

Design keys around **what is being protected**, not who is running.

---

# 6. Scope

The spec may define lock-related scope concepts (see YAML spec).

Typical scopes:

- `none` (default)
- `job`
- `flow`

However, the most common and explicit pattern is:

- Wrap a critical section with `with_lock`
- Acquire before inner step
- Release after completion

This keeps locking localized and easy to audit in YAML.

See:

→ `06-yaml-spec.md`

---

# 7. TTL Design

TTL (`ttl_seconds`) must be chosen carefully.

Too short:
- Lock may expire while still running
- Another run may enter critical section

Too long:
- Crashed process may block future runs for too long

Best practice:

- Set TTL slightly above worst-case execution time
- Prefer deterministic runtime bounds when possible
- Use monitoring to detect abnormal long-running locks

---

# 8. Locking and State

Locking is built on top of the state backend.

The same state store also handles:

- Step status
- Job status
- Resume behavior
- Crash recovery

Because locking is state-backed:

- It works across processes
- It works across scheduler-triggered runs
- It works across container restarts (as long as state DB persists)

See:

→ `17-state.md`

---

# 9. Summary

AetherFlow locking is:

- Distributed (state-backed)
- Explicit (no hidden behavior)
- TTL-based
- Fail-fast

It protects shared side-effects, not compute.

Use it when overlap can cause damage.
Avoid it when not strictly necessary.
