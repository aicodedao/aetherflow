# 92 — CI/CD, Branching, Releases, and Publishing

This document explains how CI, protected branches, automated releases, and publishing work in this repository.

It is written for contributors and maintainers.  
If you only want to submit a change, read: **Branching & PR Flow** and **What happens after merge**.

---

## 1) Branching Model

We use a strict promotion flow:

**feature/* (or any branch) → PR into `test` → PR into `master`**

Rules:

- Any branch may open a PR into `test`.
- Only `test` may open a PR into `master`.
- Direct pushes to `test` and `master` are blocked by repository rules.
- CI must be green before merge.

`test` acts as the integration/staging branch.  
`master` is production.

---

## 2) Branch Protection / Rulesets

### `test`
- PR required
- Required status checks: **CI / tests**
- (Optional) 1 approval
- No force pushes / no deletions

### `master`
- PR required
- Required status checks: **CI / tests**
- ≥ 1–2 approvals recommended
- Dismiss stale reviews
- Require conversation resolution
- Restrict PR source branches: **only `test`**
- No force pushes / no deletions

---

## 3) CI Workflow: `.github/workflows/ci.yml`

CI runs on:

- Pull Requests targeting `test` or `master`
- Pushes to `test` or `master` (e.g., merge commits)

CI is the required status check for protected branches.  
If CI is red, merges are blocked.

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

## 4) Auto Release Workflows (workflow_run)

Releases are created only after CI completes successfully on the target branch.

### `test` → RC releases
Workflow: `.github/workflows/auto-release-test.yml`

Trigger:
- `workflow_run` after **CI** completes
- Only for branch `test`
- Only for non-PR events
- Guarded to avoid loops from bot release commits

Action:
- runs `python release.py --mode rc --push`
- updates per-package versions + changelogs
- creates tags like:
    - `aetherflow-v0.1.0rc1`
    - `aetherflow-core-v0.1.0rc1`
- creates GitHub Releases marked as **pre-release**

### `master` → Final releases
Workflow: `.github/workflows/auto-release-master.yml`

Trigger:
- `workflow_run` after **CI** completes
- Only for branch `master`

Action:
- runs `python release.py --mode final --push`
- creates tags like:
    - `aetherflow-v0.1.0`
    - `aetherflow-core-v0.1.0`
- creates GitHub Releases (not prerelease)

---

## 5) Publishing to PyPI / TestPyPI

Publishing is triggered by tags (recommended pattern).

- RC tags (`*rc*`) are typically published to **TestPyPI**
- Final tags are published to **PyPI**

If you do not see publishing workflows in `.github/workflows/`,
it means this repository currently performs:
- version bump + changelog + tag + GitHub Release
  but does not upload packages to PyPI automatically.

(If publishing workflows exist, they should be documented here with the exact file names and tag patterns.)

---

## 6) `release.py` (Monorepo Release Tool)

`release.py` computes per-package releases based on:

- changes since the last package-specific tag
- Conventional Commit messages:
    - `feat:` → minor bump
    - `fix:` / `perf:` → patch bump
    - `!` or `BREAKING CHANGE` → breaking bump (configured as MINOR by default in this repo)

It then:
- updates `pyproject.toml` version
- updates `CHANGELOG.md` (Keep a Changelog format)
- commits: `release(<pkg>): <version>`
- tags: `<pkg>-v<version>`
- pushes commits and tags (when `--push` is set)
- creates GitHub Releases via the GitHub API

Important:
- RC mode must run on `test`
- Final mode must run on `master`

---

## 7) Contributor Checklist

Before opening a PR:

- Run tests locally:
    - `pytest -q`
- Ensure your branch is up-to-date with `test`
- Use clear commit messages (Conventional Commits recommended)

PR flow:

1. Open PR into `test`
2. CI must pass
3. Merge into `test`
4. A release candidate may be created automatically (RC tags)
5. When ready, open PR from `test` into `master`
6. Merge into `master`
7. A final release may be created automatically (final tags)

---

## 8) Troubleshooting

### CI passes locally but fails on GitHub
- Check Python version in CI (currently 3.11)
- Ensure dependencies are pinned in `requirements-dev.txt`

### Auto-release didn’t run
- It only triggers on successful CI runs on `test`/`master`
- It will not run on pull_request events
- It may be blocked by guard conditions to prevent loops

### Release created tags but no publish happened
- Publishing workflows may be intentionally removed/disabled
- Check `.github/workflows/` for tag-based publish jobs
