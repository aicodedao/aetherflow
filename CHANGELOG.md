# Changelog

All notable changes to **AetherFlow** are documented here.

This project follows:

- **Semantic Versioning (SemVer)**
- A strict public API boundary (`aetherflow.core.api`)
- A documented deprecation policy

See:
→ `docs/25-public-api-and-semver.md`

---

# [Unreleased]

## Breaking Changes
- None

## Added
- Built-in `external.process` step  
  - OS-level command execution (`subprocess.Popen`)
  - `timeout_seconds` + kill escalation
  - structured retry policy (`retry.max_attempts`, `retry_on_timeout`, exit code control)
  - success validation (`exit_codes`, `marker_file`, `required_files`, `forbidden_files`)
  - idempotency strategies (`marker`, `atomic_dir`)
  - structured logging modes (`inherit`, `capture`, `file`, `discard`)

## Changed
- None

## Fixed
- None

## Deprecated
- None

---

# Versioning Policy Reminder

- **PATCH**: bug fixes only, no public API changes
- **MINOR**: backward-compatible features and internal refactors
- **MAJOR**: breaking changes to public API or documented contracts

Public API surface:
```

aetherflow.core.api

```

Everything else is internal and may change in minor releases.

---

# [0.0.0] - YYYY-MM-DD

- Initial placeholder release.
- Repository scaffolding.
- Core package structure (`aetherflow-core`, `aetherflow-scheduler`, `aetherflow` meta).
