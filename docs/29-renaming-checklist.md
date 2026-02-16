# 29 — Renaming Checklist (Backend Format)

Renames are the easiest way to silently break:
- imports
- namespace layout
- CLI entrypoints
- packaging / dependency resolution

This checklist is for **any** rename that affects:
- package/module names
- distribution names
- CLI names
- public entrypoints

Treat renames as high-risk migrations.

---

## 1. Search & Update All References

When renaming anything (module, package, distribution, CLI), you must update **all** occurrences.

### 1.1 pyproject.toml

For each distribution under `packages/`:

- Update `[project]` fields:
  - `name`
  - `version` (if doing a release)
- Update console scripts in `[project.scripts]`
- Update dependencies if they refer to the old name

Example:

```toml
[project]
name = "aetherflow-core"

[project.scripts]
aetherflow = "aetherflow.core.cli:main"
````

If you rename the CLI or module paths, update here first.

---

### 1.2 Source imports (src/**)

Search the codebase for the old name and update imports.

Example patterns:

* `from aetherflow.core import ...`
* `import aetherflow.core`
* `from aetherflow.scheduler import ...`

Use ripgrep or similar:

```bash
rg "aetherflow\.core" src tests packages demo
rg "aetherflow\.scheduler" src tests packages demo
```

After a rename:

* imports must point to the new package/module path
* avoid leaving compatibility aliases unless you intentionally support both names

---

### 1.3 Tests (tests/**)

Update:

* import paths in test files
* fixtures that refer to module names
* any hardcoded CLI names used in subprocess tests (`aetherflow`, `aetherflow-scheduler`)

Example:

```python
# Before
from aetherflow.core.api import list_steps

# After (if namespace changes)
from aetherflow.core.api import list_steps
# (or whatever the new canonical path is)
```

Also update any skip markers / markers that reference old names.

---

### 1.4 Docs & Code Snippets

Docs are often the last thing to be updated and the first thing users see.

Search in:

* `.md` / `.rst` docs
* README
* examples in comments

Look for patterns like:

* `pip install aetherflow-core`
* `from aetherflow.core.api import ...`
* `aetherflow run demo/flow.yaml`

Update to match the new naming.

---

### 1.5 Demo Scripts

Check under any `demo/` or `examples/` directories:

* Python imports
* CLI calls (in shell scripts or Makefiles)
* Config/flow files that reference module/step names

Example:

```bash
aetherflow validate demo/flow.yaml
aetherflow run demo/flow.yaml
```

If CLI name changes, demo commands must follow.

---

### 1.6 CI / Pipeline Config

Update:

* GitHub Actions / other CI config
* container build scripts
* release workflows

Look for:

* `pip install aetherflow-core`
* `aetherflow ...`
* `aetherflow-scheduler ...`

Any hard-coded module or distribution name in CI must be aligned with the new naming.

---

## 2. Verify Namespace Package Layout (PEP 420)

AetherFlow uses a namespace package for the `aetherflow` top-level package.

Rules:

* **Do NOT** add `aetherflow/__init__.py` in any sub-distribution.
* Each distribution provides a subpackage:

  * `aetherflow/core`
  * `aetherflow/scheduler`
* The namespace itself is implicit (PEP 420).

If you rename or move things:

* ensure `aetherflow/` remains namespace-only
* all code lives under `aetherflow/core`, `aetherflow/scheduler`, or other subpackages — but never creates a top-level `__init__.py`.

Quick check:

* In each distribution, verify there is no `aetherflow/__init__.py`.
* There should only be `aetherflow/core/...` or `aetherflow/scheduler/...` trees.

---

## 3. Verify CLI Entry Points

The canonical CLI entrypoints must stay consistent with the package layout.

### 3.1 Core CLI

Expected mapping:

* CLI command: `aetherflow`
* Entry point: `aetherflow.core.cli:main`

In `pyproject.toml` (meta or core, depending on design):

```toml
[project.scripts]
aetherflow = "aetherflow.core.cli:main"
```

If you rename `cli` module or `main` function:

* update the entry point path
* update any tests that call the CLI directly or via `python -m`

### 3.2 Scheduler CLI

Expected mapping:

* CLI command: `aetherflow-scheduler`
* Entry point: `aetherflow.scheduler.cli:main`

In `aetherflow-scheduler` distribution:

```toml
[project.scripts]
aetherflow-scheduler = "aetherflow.scheduler.cli:main"
```

Again, any rename of:

* `aetherflow.scheduler.cli` module
* `main` callable

requires updating the entry point.

---

## 4. Post-Rename Validation (Minimal)

After applying a rename, run this sequence:

### 4.1 Editable installs

```bash
pip install -e packages/aetherflow-core
pip install -e packages/aetherflow-scheduler
pip install -e packages/aetherflow
```

### 4.2 Imports

```bash
python -c "import aetherflow.core; import aetherflow.scheduler; print('imports ok')"
```

### 4.3 CLI

```bash
aetherflow --help
aetherflow-scheduler --help
```

### 4.4 Tests

```bash
pytest -q
```

If any of these fail, you likely missed a rename target somewhere (imports, entrypoints, or namespace layout).

---

## Summary

Renaming safely requires:

* updating all references (pyproject, src, tests, docs, demos, CI)
* preserving namespace package semantics (no `aetherflow/__init__.py`)
* ensuring CLI entrypoints still point to valid modules and callables

Do not treat renames as “trivial refactors”.
Treat them as migrations and run the full checklist.

