import tempfile
import shutil
from pathlib import Path

import sys

# Allow running tests without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest
from aetherflow.core.runtime.settings import Settings


@pytest.fixture()
def temp_dir():
    d = Path(tempfile.mkdtemp(prefix="aetherflow_test_"))
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture()
def settings(temp_dir):
    return Settings(
        work_root=str(temp_dir / "work"),
        state_root=str(temp_dir / "state"),
        plugin_paths=[],
        plugin_strict=True,
        strict_templates=True,
        log_level="INFO",
    )
