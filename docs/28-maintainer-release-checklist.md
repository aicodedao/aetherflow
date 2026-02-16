# 28 — Maintainer Release Checklist (End-to-End)

This is the maintainer’s “don’t screw it up” checklist for shipping a release across:
- `aetherflow-core`
- `aetherflow-scheduler`
- `aetherflow` (meta)

Structure:
- monorepo under `packages/`
- each dist has its own `pyproject.toml`
- CLI entry points are provided by the meta + scheduler packages

Release goals:
- SemVer strict
- Public API boundary preserved (`aetherflow.core.api`)
- boring, repeatable, testable releases

---

## 0) Pre-flight (before changing anything)

- clean working tree
- on correct branch (typically `main`)
- latest `main` pulled
- CI is green for HEAD
- you have PyPI + TestPyPI credentials configured for `twine`

Recommended tooling:

```bash
python -m pip install --upgrade build twine
````

---

## 1) Bump versions (core / scheduler / meta)

Update versions in:

* `packages/aetherflow-core/pyproject.toml`
* `packages/aetherflow-scheduler/pyproject.toml`
* `packages/aetherflow/pyproject.toml`

Also update dependency ranges so they stay satisfiable:

* scheduler depends on core
* meta depends on core + scheduler

Rule:

* publish order will be core → scheduler → meta, so make sure ranges reflect the new release.

Commit version bumps:

```bash
git add -A
git commit -m "release: bump versions"
```

---

## 2) Update CHANGELOG.md

Edit repository CHANGELOG to include:

* release date
* changes grouped:

    * Breaking Changes
    * Added
    * Fixed
    * Deprecated
    * Security (if any)
* migration notes if breaking

Commit:

```bash
git add CHANGELOG.md
git commit -m "docs: changelog for release"
```

---

## 3) Run tests (full suite)

From repo root:

```bash
pytest -q
```

Must be green. No “ship anyway”.

---

## 4) Editable install smoke (local dev wiring)

This ensures packaging + imports work inside a real environment.

```bash
pip install -e packages/aetherflow-core
pip install -e packages/aetherflow-scheduler
pip install -e packages/aetherflow
```

Quick import sanity:

```bash
python -c "import aetherflow.core; import aetherflow.scheduler; print('ok')"
```

---

## 5) CLI smoke

Core CLI surface is expected via `aetherflow` (meta) and scheduler via `aetherflow-scheduler`.

```bash
aetherflow --help
aetherflow validate demo/flow.yaml || true
aetherflow run demo/flow.yaml || true

aetherflow-scheduler --help
```

Notes:

* `validate` should parse and list steps/connectors
* demo flows may fail in your local env (missing DB creds etc.), but CLI must start and error cleanly

---

## 6) Build (sdist + wheel)

Build each dist:

```bash
python -m build packages/aetherflow-core
python -m build packages/aetherflow-scheduler
python -m build packages/aetherflow
```

Verify each produced:

* `.whl`
* `.tar.gz`

Check the `dist/` folder inside each package directory.

---

## 7) Upload to TestPyPI → install clean → run demo smoke

### 7.1 Upload (order matters)

```bash
twine upload --repository testpypi packages/aetherflow-core/dist/*
twine upload --repository testpypi packages/aetherflow-scheduler/dist/*
twine upload --repository testpypi packages/aetherflow/dist/*
```

### 7.2 Clean install from TestPyPI

Fresh venv (no repo path contamination):

```bash
python -m venv .venv-testpypi
source .venv-testpypi/bin/activate
python -m pip install --upgrade pip
```

Install the meta package (it should pull correct deps):

```bash
python -m pip install --index-url https://test.pypi.org/simple \
                      --extra-index-url https://pypi.org/simple \
                      aetherflow==<version>
```

### 7.3 Smoke tests from installed artifacts

Imports:

```bash
python -c "import aetherflow.core; import aetherflow.scheduler; print('core', aetherflow.core.__version__)"
```

Registry:

```bash
python -c "from aetherflow.core.api import list_steps, list_connectors; print(list_steps()); print(list_connectors())"
```

CLI:

```bash
aetherflow --help
aetherflow validate demo/flow.yaml || true
aetherflow-scheduler --help
```

Optional: run a demo flow that has zero external dependencies (recommended to keep one in `demo/`).

---

## 8) Upload to PyPI (production)

If TestPyPI is clean, publish to PyPI in the same order:

```bash
twine upload packages/aetherflow-core/dist/*
twine upload packages/aetherflow-scheduler/dist/*
twine upload packages/aetherflow/dist/*
```

---

## 9) Tag + push tags

Tag should match your release convention.

Recommended:

* `vX.Y.Z` for meta release (or core if you treat it as primary)
* plus optional per-package tags if you want

Example:

```bash
git tag v<version>
git push origin v<version>
```

---

# Final sanity checklist (quick)

* [ ] Versions bumped in all 3 packages
* [ ] Dependency ranges updated (scheduler→core, meta→core+scheduler)
* [ ] CHANGELOG updated and committed
* [ ] `pytest -q` green
* [ ] Editable install works
* [ ] CLI starts and errors cleanly
* [ ] Wheels and sdists built for all 3
* [ ] TestPyPI install works in clean venv
* [ ] Demo/CLI smoke passes from TestPyPI artifacts
* [ ] PyPI upload done in correct order
* [ ] Tags pushed

If you follow this checklist, releases stay boring — which is exactly what you want.

