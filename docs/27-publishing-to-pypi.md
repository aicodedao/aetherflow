# 27 — Publishing to PyPI (Backend Format)

This doc describes how to publish the three PyPI distributions for this project:

- `aetherflow-core`   (core engine, builtins, API)
- `aetherflow-scheduler` (scheduler / runner integration)
- `aetherflow`        (meta package that pulls everything together)

Publishing order **must** be:

1. `aetherflow-core`
2. `aetherflow-scheduler`
3. `aetherflow` (meta)

So that dependency constraints are always satisfiable.

---

## Shared Pre-Reqs

Before any publish:

- You are on the correct branch (usually `main` / `release`).
- Working tree clean.
- Version bumps already committed.
- You have valid PyPI + TestPyPI credentials configured for `twine`.

Recommended tools:

```bash
python -m pip install --upgrade build twine
````

---

# 1. Publishing `aetherflow-core`

This is the foundational distribution: core engine, builtins, public API.

## 1.1 Bump version

Update version in the core package (single source of truth in core):

* `packages/aetherflow-core/pyproject.toml` (or equivalent version file)

Example:

```toml
[project]
name = "aetherflow-core"
version = "2.3.0"
```

Commit this change before building.

## 1.2 Build sdist + wheel

From the root or from the core package directory (depending on repo layout).
Assuming monorepo with subpackage:

```bash
cd packages/aetherflow-core
python -m build
```

This should create:

* `dist/aetherflow-core-<version>.tar.gz`
* `dist/aetherflow-core-<version>-py3-none-any.whl`

## 1.3 Upload to TestPyPI

```bash
twine upload --repository testpypi dist/*
```

Verify upload succeeds.

## 1.4 Smoke test from TestPyPI

Create a fresh virtualenv (no local repo imports):

```bash
python -m venv .venv-test-core
source .venv-test-core/bin/activate  # Windows: .venv-test-core\Scripts\activate
python -m pip install --upgrade pip
python -m pip install --index-url https://test.pypi.org/simple \
                      --extra-index-url https://pypi.org/simple \
                      aetherflow-core==<version>
```

Then run a minimal CLI smoke:

```bash
aetherflow validate --help
aetherflow run --help
```

If your CLI entry point lives on the meta package instead, adjust to:

```bash
python -c "import aetherflow.core; print(aetherflow.core.__version__)"
```

Core smoke test should verify:

* package can be imported
* public API can be accessed

Example:

```bash
python -c "from aetherflow.core.api import list_steps, list_connectors; print('steps:', list_steps()); print('connectors:', list_connectors())"
```

## 1.5 Upload to PyPI (production)

When TestPyPI smoke is good:

```bash
twine upload dist/*
```

Tag the release:

```bash
cd /path/to/repo/root
git tag v<core-version>
git push origin v<core-version>
```

---

# 2. Publishing `aetherflow-scheduler`

Scheduler depends on `aetherflow-core` (with a compatible `>=` range).

## 2.1 Ensure dependency constraint is correct

Check `packages/aetherflow-scheduler/pyproject.toml`:

```toml
[project]
name = "aetherflow-scheduler"

[project.dependencies]
aetherflow-core = ">=2.3.0,<3.0.0"
```

Update as needed to match the newly released core version.

Then bump scheduler version:

```toml
[project]
version = "1.5.0"
```

Commit changes.

## 2.2 Build scheduler distribution

```bash
cd packages/aetherflow-scheduler
python -m build
```

Artifacts:

* `dist/aetherflow-scheduler-<version>.tar.gz`
* `dist/aetherflow-scheduler-<version>-py3-none-any.whl`

## 2.3 Upload to TestPyPI

```bash
twine upload --repository testpypi dist/*
```

## 2.4 Smoke test scheduler from TestPyPI

New clean venv:

```bash
python -m venv .venv-test-scheduler
source .venv-test-scheduler/bin/activate
python -m pip install --upgrade pip
python -m pip install --index-url https://test.pypi.org/simple \
                      --extra-index-url https://pypi.org/simple \
                      aetherflow-scheduler==<version>
```

Validate imports:

```bash
python -c "import aetherflow.scheduler; print('scheduler version:', getattr(aetherflow.scheduler, '__version__', 'unknown'))"
```

If the scheduler ships a CLI entry point (for example `aetherflow-scheduler`):

```bash
aetherflow-scheduler --help
aetherflow-scheduler run --help
```

Minimal smoke run example (adjust to actual CLI):

```bash
aetherflow-scheduler run --dry-run
```

## 2.5 Upload scheduler to PyPI

When TestPyPI smoke passes:

```bash
twine upload dist/*
```

Tag:

```bash
cd /path/to/repo/root
git tag scheduler-v<version>
git push origin scheduler-v<version>
```

(Tag naming is up to your convention; the key is that it’s unambiguous.)

---

# 3. Publishing `aetherflow` (meta package)

The meta package is the “batteries-included” entry point.

It depends on:

* `aetherflow-core`
* `aetherflow-scheduler`

## 3.1 Check meta dependencies

In `packages/aetherflow/pyproject.toml`:

```toml
[project]
name = "aetherflow"

[project.dependencies]
aetherflow-core = ">=2.3.0,<3.0.0"
aetherflow-scheduler = ">=1.5.0,<2.0.0"
```

Update ranges to match newly released versions and bump meta version:

```toml
[project]
version = "2.3.0"
```

Commit.

## 3.2 Build meta distribution

```bash
cd packages/aetherflow
python -m build
```

Artifacts:

* `dist/aetherflow-<version>.tar.gz`
* `dist/aetherflow-<version>-py3-none-any.whl`

## 3.3 Upload meta to TestPyPI

```bash
twine upload --repository testpypi dist/*
```

## 3.4 Smoke test meta from TestPyPI

Fresh venv:

```bash
python -m venv .venv-test-meta
source .venv-test-meta/bin/activate
python -m pip install --upgrade pip
python -m pip install --index-url https://test.pypi.org/simple \
                      --extra-index-url https://pypi.org/simple \
                      aetherflow==<version>
```

Verify imports:

```bash
python -c "import aetherflow.core; import aetherflow.scheduler; print('core:', aetherflow.core.__version__); print('scheduler:', getattr(aetherflow.scheduler, '__version__', 'unknown'))"
```

If the main CLI lives on the meta package, smoke that as well:

```bash
aetherflow --help
aetherflow validate --help
aetherflow run --help
```

## 3.5 Upload meta to PyPI

```bash
twine upload dist/*
```

Tag:

```bash
cd /path/to/repo/root
git tag v<meta-version>
git push origin v<meta-version>
```

---

# Summary — End-to-End Flow

1. **Core**

    * bump `aetherflow-core` version
    * build → TestPyPI → smoke → PyPI

2. **Scheduler**

    * align `aetherflow-core` dependency range
    * bump `aetherflow-scheduler` version
    * build → TestPyPI → smoke (scheduler CLI/import) → PyPI

3. **Meta (`aetherflow`)**

    * align `aetherflow-core` + `aetherflow-scheduler` ranges
    * bump meta version
    * build → TestPyPI → smoke (imports + CLI) → PyPI

If any smoke test fails at a stage, fix → rebuild → re-upload to **TestPyPI** first. Only when TestPyPI is clean do you push to the main PyPI index.
