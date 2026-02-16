# Contributing

Thanks for helping make **AetherFlow** more boring, predictable, and safe.

This project prioritizes:

- Deterministic execution
- Strict templating contracts
- Stable public API boundaries
- Explicit failure behavior
- SemVer discipline

If you contribute, you are contributing to those guarantees.

---

# Development Setup

## Clone and install (editable mode)

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

pip install -e packages/aetherflow-core[dev]
pip install -e packages/aetherflow-scheduler[dev]
pip install -e packages/aetherflow
````

Optional: install extras if your change touches reporting or optional connectors.

---

## Run tests

```bash
pytest -q -m "not slow"
```

All tests must pass before submitting a PR.

Core test categories include:

* CLI validation
* Template resolution contract
* State + resume semantics
* Built-in steps/connectors
* Guardband tests (architecture constraints)
* Public API contract tests

If you change behavior, you must update or extend tests accordingly.

---

# Changing Behavior

If your change affects:

* YAML schema
* Step/connector contract
* CLI behavior
* Public API (`aetherflow.core.api`)
* Template resolution rules
* State semantics

You must:

1. Update tests
2. Update documentation
3. Update `CHANGELOG.md`

---

# Public API Rules

Stable import surface:

```python
from aetherflow.core.api import ...
```

Everything else is internal.

If you modify anything exposed through:

```
aetherflow.core.api
```

You must follow:

→ `docs/25-public-api-and-semver.md`

This includes:

* deprecation warnings before removal
* migration notes
* major version bump for breaking changes
* updating API contract tests

---

# Labels & Release Hygiene

All PRs must have at least one primary label:

* `bug`
* `feature`
* `breaking`
* `docs`
* `chore`
* `security`

Labeling rules:

→ `docs/31-labeling-guide.md`

If your PR is labeled `breaking`, it must include:

* Migration notes
* Tests
* Explicit CHANGELOG entry

No exceptions.

# CI/CD and Releases

This repo uses a strict promotion flow:

**any branch → PR into `test` → PR into `master`**

CI must be green to merge. Releases are created automatically after CI succeeds on `test` (RC) and `master` (final).

Read the full details: `docs/32-ci-cd.md`.

```
develop -> test -> master
           ↓
      auto-release
           ↓
      tag created
           ↓
    publish workflow
           ↓
     PyPI/TestPyPI
```

---

# Templating Contract

Templating is strict by design:

Only allowed:

```
{{VAR}}
{{VAR:DEFAULT}}
```

Anything else must fail fast.

If you modify resolution behavior:

* update `docs/99-strict-templating.md`
* update resolution tests
* confirm no backward-incompatible behavior slips into a minor release

---

# State & Resume Safety

State guarantees are core to AetherFlow.

If you touch:

* runner logic
* state schema
* lock acquisition
* resume semantics

You must:

* test resume with same `run_id`
* test partial failure recovery
* verify no duplicate execution occurs

Reference:

* `docs/17-state.md`
* `docs/404-Failure-Recovery-Playbook.md`

---

# Guardrails

The repository includes guardband tests to prevent:

* legacy syntax reintroduction
* API surface creep
* templating regressions

Do not bypass guard tests unless absolutely necessary, and document why.

---

# Commit Guidelines

Keep commits:

* small
* focused
* explicit in intent

If a commit changes user-visible behavior, mention it in:

```
CHANGELOG.md
```

---

# Pull Request Checklist

Before submitting:

* [ ] Tests pass locally
* [ ] Public API unchanged or properly versioned
* [ ] Docs updated if needed
* [ ] CHANGELOG updated
* [ ] Labels applied
* [ ] No accidental namespace/package changes

---

# Design Philosophy Reminder

AetherFlow values:

* Explicit > implicit
* Deterministic > clever
* Config-over-code
* Fail-fast over silent fallback
* Boring releases

If your change increases hidden behavior or implicit magic, it likely needs revision.

Thanks for keeping it boring.
