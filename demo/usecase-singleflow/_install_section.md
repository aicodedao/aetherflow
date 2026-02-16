## 1) Install

You can run the demo in three ways.

### A) Install from PyPI (end users)

```bash
python -m pip install -U pip
pip install "aetherflow-core[all]" aetherflow-scheduler
```

### B) Install from TestPyPI (maintainers / pre-release validation)

```bash
python -m pip install -U pip
pip install -i https://test.pypi.org/simple \
  --extra-index-url https://pypi.org/simple \
  "aetherflow-core[all]" aetherflow-scheduler
```

### C) Install from source (editable, for development)

From repo root:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate

pip install -e packages/aetherflow-core[all,dev]
pip install -e packages/aetherflow-scheduler[dev]
```
