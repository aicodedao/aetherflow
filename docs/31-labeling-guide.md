# 31 — Labeling Guide (Backend Format)

Goal:
- clear triage
- predictable SemVer impact
- clean release notes

This guide defines the canonical label set for this repo and the rules maintainers should enforce.

---

# Canonical Labels

## `bug`
Use for:
- user-facing defects
- incorrect behavior vs documented contract
- crashes / exceptions in normal usage
- regression fixes

SemVer impact:
- **PATCH** (default)

Notes:
- If bugfix changes public behavior materially, call it out in CHANGELOG even if still patch.

---

## `feature`
Use for:
- new backward-compatible functionality
- new step/connector (additive)
- new optional inputs with safe defaults
- performance improvements that do not change public contract

SemVer impact:
- **MINOR** (default)

Notes:
- If the feature introduces new config fields, update docs and add tests.

---

## `breaking`
Use for:
- any non-backward-compatible change to:
    - `aetherflow.core.api` (public API)
    - step YAML schemas (removing/renaming fields, changing meaning)
    - connector config contracts
    - plugin extension contract
- removal of previously deprecated public symbols

SemVer impact:
- **MAJOR** (required)

Hard rules:
- PR must include **migration notes**
- PR must include **tests** covering:
    - new behavior
    - failure mode for old behavior (where applicable)
- PR must be explicitly called out in CHANGELOG under **Breaking Changes**

---

## `docs`
Use for:
- documentation-only changes
- README updates
- examples + guides
- comment fixes if they do not change runtime behavior

SemVer impact:
- **no release bump by itself**, unless you bundle it with other changes

Notes:
- Docs PRs should still be reviewed for correctness and alignment with runtime behavior.

---

## `chore`
Use for:
- refactors
- CI / tooling changes
- formatting, linting, dependency pin bumps
- infra work
- test refactors that don’t change runtime behavior

SemVer impact:
- usually **PATCH** or **no bump**
- if a refactor introduces a new public feature, it becomes `feature`

Notes:
- Chore PRs should not sneak in behavior changes. If they do, label must reflect it (`bug`/`feature`/`breaking`).

---

## `security`
Use for:
- vulnerability fixes
- secrets handling / redaction hardening
- plugin path trust boundary changes
- supply chain changes (dependency replacement due to CVE)

SemVer impact:
- depends on scope:
    - **PATCH** if fix is backward-compatible
    - **MINOR** if new opt-in security behavior is added
    - **MAJOR** if enforcement becomes stricter and breaks configs

Hard rules:
- include a short security note in CHANGELOG (no sensitive details if embargoed)
- add tests for the security behavior

---

# Label → Release Notes Mapping

Recommended release note sections:

- Breaking Changes  ← `breaking`
- Added            ← `feature`
- Fixed            ← `bug`
- Security         ← `security`
- Docs             ← `docs`
- Maintenance      ← `chore`

---

# Required PR Rules

## 1) Every PR must have at least one primary label
Primary labels:
- `bug`, `feature`, `breaking`, `docs`, `chore`, `security`

(Secondary labels are allowed, but one primary is mandatory.)

## 2) `breaking` PRs are gated
A PR with `breaking` must include:
- migration notes (before/after examples)
- tests covering new contract
- explicit CHANGELOG entry

No exceptions.

## 3) Label must match SemVer impact
If maintainers disagree:
- err on the stricter interpretation (upgrade impact)
- or split the PR into smaller ones

---

# Maintainer Triage Checklist

When reviewing labels, ask:

1. Does this change modify a public contract?
    - yes → `breaking`
2. Is it purely additive and backward-compatible?
    - yes → `feature`
3. Is it a bugfix/regression?
    - yes → `bug`
4. Is it docs-only?
    - yes → `docs`
5. Is it infra/refactor/tooling?
    - yes → `chore`
6. Is it security-related?
    - yes → `security`

If none apply, the PR is underspecified — request clarification in the PR description.

---

# Summary

Labels are not decoration.
They are how maintainers keep releases boring, predictable, and SemVer-correct.

Hard rule:
- `breaking` label = migration notes + tests + changelog callout.
