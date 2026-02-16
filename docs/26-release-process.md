# 26 — Release Process (Principles & Best Practice)

This document defines how AetherFlow releases should be performed.

Goals:
- No surprises
- No accidental breakage
- No undocumented behavior changes
- Public API stability guaranteed

Public API surface:
- `aetherflow.core.api`

Everything else is internal.

---

# Core Release Principles

## 1. Public API Is Sacred

Only symbols exported from:

```python
aetherflow.core.api
````

are covered by backward compatibility guarantees.

If you change anything here:

* it must follow SemVer rules
* it must be documented
* it must be tested
* it must be migration-safe

---

## 2. Strict Semantic Versioning

Version format:

```text
MAJOR.MINOR.PATCH
```

Rules:

* PATCH → bugfix only
* MINOR → backward-compatible features
* MAJOR → breaking public API changes

No gray areas.

If unsure → bump minor.
If breaking → bump major.

---

# Breaking Change Policy

A breaking change is any modification that:

* changes a public API signature
* changes documented behavior of a public contract
* alters YAML schema in a non-backward-compatible way
* changes extension/plugin contract
* removes a deprecated public symbol

If a breaking change exists, the release MUST:

### 1. Bump MAJOR version

Example:

```text
2.4.3 → 3.0.0
```

### 2. Call out clearly in CHANGELOG

Required structure:

```text
## [3.0.0] - 2026-02-15

### Breaking Changes
- Removed deprecated register_connector_v1
- external.process idempotency strategy now requires explicit strategy

### Migration Notes
- Replace register_connector_v1 with register_connector
- Update YAML to include idempotency.strategy

### Why
- Consistency and explicitness improvements
```

No silent breaking changes.

### 3. Provide Migration Notes

Migration must:

* describe old behavior
* describe new behavior
* show before/after example

Example:

```yaml
# Before
type: external.process
timeout_seconds: 3600

# After
type: external.process
inputs:
  timeout_seconds: 3600
```

### 4. Add Test Coverage

Breaking changes must include:

* regression tests
* migration validation tests
* negative case tests

No release without coverage.

---

# Deprecation Flow

Before removing a public API:

1. Mark deprecated in code.

```python
import warnings

warnings.warn(
    "register_step_v1 is deprecated and will be removed in v3.0",
    DeprecationWarning,
    stacklevel=2,
)
```

2. Document deprecation in CHANGELOG (under "Deprecated").
3. Keep for at least one minor release.
4. Remove only in next major.

---

# Release Checklist (Boring Is Good)

A release should feel procedural and uneventful.

## Step 1 — Lock version

* Update version in package metadata.
* Ensure version matches tag to be created.

## Step 2 — Run Full Test Suite

```bash
pytest
```

Tests must:

* pass locally
* pass in CI
* include external.process, reporting, db connectors

No partial green.

## Step 3 — Run Demo Smoke

Run minimal example flows:

```bash
python demo/run_basic.py
```

Validate:

* state db initializes
* steps register
* connectors resolve
* external.process works
* reporting works

Smoke tests should validate:

* flow execution
* resume
* failure handling
* lock behavior

---

## Step 4 — Validate Public API Stability

Quick sanity:

```python
from aetherflow.core.api import list_steps, list_connectors
print(list_steps())
print(list_connectors())
```

Ensure:

* expected builtins are present
* no accidental removals

---

## Step 5 — Build Artifact

```bash
python -m build
```

Verify:

* wheel builds
* metadata correct
* no accidental dev files included

---

## Step 6 — Publish

```bash
twine upload dist/*
```

Tag release:

```bash
git tag vX.Y.Z
git push origin vX.Y.Z
```

Tag must match package version exactly.

---

# What a Good Release Looks Like

* Clean version bump
* Clear CHANGELOG entry
* No undocumented behavior shifts
* Tests passing
* Demo flow still works
* Public API untouched unless intentionally changed

---

# What a Bad Release Looks Like

* Patch version introduces breaking YAML change
* Minor release removes public function
* No migration notes
* Silent behavior change
* Tests updated but docs not

If users are surprised, release failed.

---

# Stability Contract Summary

Public boundary:

```python
aetherflow.core.api
```

SemVer enforced strictly.

Breaking change requires:

* MAJOR bump
* CHANGELOG callout
* Migration notes
* Tests

Release process should be:

* Predictable
* Repeatable
* Boring

Boring releases are a feature, not a bug.
