# Contributing

Thanks for helping make **AetherFlow** more boring, predictable, and safe.

This project prioritizes:

* Deterministic execution
* Strict templating contracts
* Stable public API boundaries
* Explicit failure behavior
* SemVer discipline

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
```

Install optional extras only if your change touches reporting, publishing, or optional connectors.

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
* Step or connector contract
* CLI behavior
* Public API (`aetherflow.core.api`)
* Template resolution rules
* State semantics
* Release logic

You must:

1. Update tests
2. Update documentation
3. Update `CHANGELOG.md`

Breaking changes must include migration notes.

---

# Public API Rules

Stable import surface:

```python
from aetherflow.core.api import ...
```

Everything else is internal and may change without notice.

If you modify anything exposed through:

```
aetherflow.core.api
```

You must follow:

→ `docs/25-public-api-and-semver.md`

This includes:

* Deprecation warnings before removal
* Migration documentation
* Major version bump for breaking changes
* Updating API contract tests

No silent breaking changes.

---

# Labels & Release Hygiene

All PRs must include at least one primary label:

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
* Updated tests
* Explicit CHANGELOG entry

No exceptions.

---

# CI/CD and Releases

This repository uses a strict promotion flow:

```
any branch → PR into test → PR into master
```

CI must be green to merge.

Releases are automated:

* Push to `test` → RC release on `release-test` + `*-v*rc*` tags → TestPyPI
* Push to `master` → Final release on `release` + `*-v*` tags → PyPI

Publishing is tag-driven.

Full details:

→ `docs/92-ci-cd-branching-releases.md`

Release automation is branch-based and does not push to protected branches directly.

---

# Templating Contract

Templating is strict by design.

Only allowed syntax:

```
{{VAR}}
{{VAR:DEFAULT}}
```

Anything else must fail fast.

If you modify resolution behavior:

* Update `docs/99-strict-templating.md`
* Update resolution tests
* Ensure no backward-incompatible behavior slips into a minor release

This contract is non-negotiable.

---

# State & Resume Safety

State guarantees are core to AetherFlow.

If you touch:

* Runner logic
* State schema
* Lock acquisition
* Resume semantics
* Failure recovery logic

You must:

* Test resume with the same `run_id`
* Test partial failure recovery
* Verify no duplicate execution occurs
* Confirm idempotency

References:

* `docs/17-state.md`
* `docs/404-failure-recovery-playbook.md`

Silent corruption is worse than explicit failure.

---

# Release Script (`release.py`) Guidelines

The release system:

* Computes per-package versions from Conventional Commits
* Updates `pyproject.toml`
* Updates `CHANGELOG.md`
* Commits on `release-*` branches
* Creates per-package tags
* Pushes branch + tags
* Optionally creates GitHub Releases

Hard failures must stop execution:

* Dirty working tree (unless explicitly allowed)
* Base branch mismatch with `origin`
* Cannot push release branch
* Cannot push tag

Warnings (non-fatal):

* Detached HEAD (common in CI)
* Failure to create GitHub Release via API

Release automation must remain deterministic and idempotent.

---

# Guardrails

The repository includes guard tests to prevent:

* Legacy syntax reintroduction
* API surface creep
* Templating regressions
* Architecture violations

Do not bypass guard tests unless absolutely necessary, and document why.

---

# Commit Guidelines

Keep commits:

* Small
* Focused
* Explicit in intent

Use Conventional Commit style where possible:

```
feat:
fix:
perf:
docs:
refactor:
chore:
```

If a commit changes user-visible behavior, it must be reflected in:

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
* [ ] No protected branch pushes

---

# Design Philosophy Reminder

AetherFlow values:

* Explicit > implicit
* Deterministic > clever
* Config over magic
* Fail-fast over silent fallback
* Boring releases
* Predictable automation

If your change introduces hidden behavior, implicit side effects, or silent fallbacks, it likely needs revision.

Thanks for keeping it boring.
