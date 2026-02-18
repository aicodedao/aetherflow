# 32 — CI/CD, Branching, Releases, and Publishing

This document explains how CI, protected branches, automated releases, and publishing work in this repository.

It is written for contributors and maintainers.
If you only want to submit a change, read: **Branching & PR Flow** and **What happens after merge**.

---

# 1) Branching Model

We use a strict promotion flow:

```
feature/*  →  PR into test  →  PR into master
```

Rules:

* Any branch may open a PR into `test`.
* Only `test` may open a PR into `master`.
* Direct pushes to `test` and `master` are blocked.
* CI must be green before merge.

Branch roles:

* `test` = integration / staging
* `master` = production

Release branches:

* `release-test` = RC releases (TestPyPI)
* `release` = final releases (PyPI)

---

# 2) Branch Protection / Rulesets

## `test`

* Pull Request required
* Required status checks: **CI / tests**
* (Optional) ≥1 approval
* No force pushes
* No branch deletions

## `master`

* Pull Request required
* Required status checks: **CI / tests**
* ≥1–2 approvals recommended
* Dismiss stale reviews
* Require conversation resolution
* Restrict PR source branches: **only `test`**
* No force pushes
* No deletions

## `release-test` and `release`

These are automation branches.

Rules:

* ❌ Block user direct pushes
* ❌ Block force pushes
* ❌ Block deletions
* ✅ Allow **GitHub Actions** to push (via ruleset bypass / actor allowlist)
* Admins may bypass if necessary

These branches are modified only by automation.

---

# 3) CI Workflow

File: `.github/workflows/ci.yml`

CI runs on:

* Pull requests targeting `test` or `master`
* Pushes to `test` or `master`
* `workflow_dispatch` (manual)

CI is the required status check for protected branches.

If CI fails:

* PR merge is blocked
* Release automation will not run

Minimal CI best practices:

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0

- uses: actions/setup-python@v5
  with:
    python-version: "3.11"

- run: pytest -q -m "not slow"
```

---

# 4) Auto Release (Branch-Based Model)

This repository uses a **branch-based release flow** to avoid pushing to protected branches.

## Overview

### RC Releases (TestPyPI)

1. PR merges into `test`
2. Push to `test` triggers auto-release workflow
3. Workflow:

  * resets local checkout to `origin/test`
  * creates or resets `release-test` at same commit SHA
  * bumps versions + updates changelogs
  * commits to `release-test`
  * pushes `release-test`
  * creates tags: `*-v*rc*`
4. Tag push triggers publish workflow
5. Packages uploaded to **TestPyPI**

### Final Releases (PyPI)

Same process, but:

* Base branch: `master`
* Release branch: `release`
* Tags: `*-v*` (non-rc)
* Upload target: **PyPI**

---

# 5) Tag-Based Publishing

Publishing workflows trigger on tags.

## RC → TestPyPI

```yaml
on:
  push:
    tags:
      - "*-v*rc*"
```

## Final → PyPI

```yaml
on:
  push:
    tags:
      - "*-v*"

jobs:
  publish:
    if: ${{ !contains(github.ref_name, 'rc') }}
```

Each tag corresponds to a single package in the monorepo:

```
aetherflow-v0.1.0rc1
aetherflow-core-v0.1.0rc1
aetherflow-scheduler-v0.1.0rc1
```

The publish workflow must:

* Checkout with `fetch-depth: 0`
* Use `fetch-tags: true`
* Parse package name from tag
* Build only that package
* Upload only that package

---

# 6) Loop Prevention (CRITICAL)

Release commits and tag pushes can trigger workflows again.

To prevent infinite loops:

### Option A — Actor Guard (Recommended)

Skip release job if triggered by bot:

```yaml
if: ${{ github.actor != 'github-actions[bot]' }}
```

### Option B — Commit Message Guard

Release commits use predictable messages:

```
release(<pkg>): <version>
```

You may filter on this message to avoid recursion.

### Option C — workflow_run Guard

If using `workflow_run`, check:

```yaml
if: >
  github.event.workflow_run.conclusion == 'success' &&
  github.event.workflow_run.head_branch == 'test' &&
  github.event.workflow_run.actor.login != 'github-actions[bot]'
```

Without loop guards, your release workflow will retrigger itself endlessly.

---

# 7) `release.py` Behavior and Failure Policy

`release.py` is branch-based (no PR API required).

It:

1. Resets to `origin/<base-branch>`
2. Verifies base branch matches remote
3. Creates or resets `release-branch` at same SHA
4. Computes per-package release plan
5. Updates:

  * `pyproject.toml`
  * `CHANGELOG.md`
6. Commits on `release-branch`
7. Pushes branch
8. Creates and pushes tags
9. Optionally creates GitHub Releases

## Hard Failures (raise / stop)

The script stops on:

* Dirty working tree (unless `--allow-dirty`)
* Missing remote base branch
* Base branch local HEAD ≠ `origin/<base>` (unless `--skip-base-sync-check`)
* Cannot create/reset release branch
* Cannot commit changes
* Cannot push release branch
* Cannot push tag

These are critical integrity failures.

## Warnings (continue)

The script logs warnings for:

* Detached HEAD (common in GitHub Actions)
* Failure to create GitHub Release via API
* Tag already exists on remote

Publishing depends only on tags — not GitHub Releases.

---

# 8) Concurrency and Duplicate Runs

To avoid overlapping release runs:

```yaml
concurrency:
  group: auto-release-${{ github.ref }}
  cancel-in-progress: true
```

Release branches may be:

* Long-lived (`release-test`)
* Or per-run unique (`release/rc-YYYYMMDD-<sha>`)

If using long-lived release branches:

* Always reset branch to base SHA
* Never manually edit release branch

---

# 9) Manual Release (Local)

RC:

```bash
python release.py \
  --mode rc \
  --base-branch test \
  --release-branch release-test \
  --push
```

Final:

```bash
python release.py \
  --mode final \
  --base-branch master \
  --release-branch release \
  --push
```

Without `--push`, changes are local only.

---

# 10) Maintainer Checklist

Before enabling automation:

* Protect `test` and `master`
* Allow GitHub Actions to push to `release-test` and `release`
* Confirm publish workflows exist
* Confirm tag patterns are correct
* Add loop-prevention guards
* Test with dry run first

---

# 11) Troubleshooting

## Auto-release didn’t run

* It only triggers on successful CI runs
* Check branch filters
* Check actor guards

## Release created tags but publish didn’t run

* Verify publish workflow matches tag pattern
* Ensure publish workflow checks out with `fetch-tags: true`

## Push failed on release branch

* Check branch ruleset
* Ensure GitHub Actions is allowed to push

## CI mismatch error

* Ensure release runs from exact `origin/<base>` commit
* Ensure no manual rebase happened between CI and release

---

# Final Architecture Summary

```
feature/* → PR → test → auto-release (release-test + rc tags)
                                 ↓
                          TestPyPI publish

test → PR → master → auto-release (release + final tags)
                                 ↓
                             PyPI publish
```

This model:

* Keeps protected branches clean
* Avoids PR API auto-merge complexity
* Produces deterministic, boring, reproducible releases
* Works cleanly with branch protection rules
