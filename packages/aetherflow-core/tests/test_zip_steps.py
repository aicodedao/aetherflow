from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from aetherflow.core.context import RunContext
from aetherflow.core.connectors.manager import Connectors
from aetherflow.core.state import StateStore
from aetherflow.core.builtins.steps import ZipCreate, ZipExtract


def _has_encrypted_zip_backend() -> bool:
    # system tools
    if shutil.which("zip") and shutil.which("unzip"):
        return True
    # optional pure python
    try:
        import pyzipper  # noqa: F401

        return True
    except Exception:
        return False


def _ctx(settings, tmp: Path):
    state = StateStore(str(tmp / "state.sqlite"))
    # Provide a canonical archive connector for built-in zip/unzip steps.
    # Prefer pyzipper (pure Python, supports encryption), fallback to os tools, else zipfile.
    driver = "zipfile"
    try:
        import pyzipper  # noqa: F401

        driver = "pyzipper"
    except Exception:
        if shutil.which("zip") and shutil.which("unzip"):
            driver = "os"

    resources = {
        "archive_default": {
            "kind": "archive",
            "driver": driver,
            "config": {},
            "options": {},
        }
    }
    ctx = RunContext(
        settings=settings,
        flow_id="f",
        run_id="r123",
        work_root=tmp,
        layout={"artifacts": "artifacts", "scratch": "scratch", "manifests": "manifests"},
        state=state,
        resources=resources,
        connectors={},
    )
    ctx.connectors = Connectors(ctx=ctx, resources=resources, settings=settings)
    return ctx


def test_zip_unzip_no_password(temp_dir, settings):
    ctx = _ctx(settings, temp_dir)
    job_id = "job"
    base = ctx.artifacts_dir(job_id)
    (base / "in").mkdir(parents=True, exist_ok=True)
    (base / "in/a.txt").write_text("a")
    (base / "in/b.txt").write_text("b")

    z = ZipCreate(
        "z",
        {
            "dest_path": "out/test.zip",
            "items": ["in/*.txt"],
            "src_dir": ".",
        },
        ctx,
        job_id,
    )
    out = z.run()
    assert Path(out["output"]).exists()

    u = ZipExtract(
        "u",
        {
            "archives": ["out/test.zip"],
            "src_dir": ".",
            "dest_dir": "out/extracted",
        },
        ctx,
        job_id,
    )
    uout = u.run()
    assert (Path(uout["dest_dir"]) / "out/in/a.txt").read_text() == "a"
    assert (Path(uout["dest_dir"]) / "out/in/b.txt").read_text() == "b"


def test_zip_unzip_with_password(temp_dir, settings):
    if not _has_encrypted_zip_backend():
        pytest.skip("Encrypted zip tests require system 'zip'/'unzip' or optional 'pyzipper' dependency")
    ctx = _ctx(settings, temp_dir)
    job_id = "job"
    base = ctx.artifacts_dir(job_id)
    (base / "data").mkdir(parents=True, exist_ok=True)
    (base / "data/secret.txt").write_text("shh")

    z = ZipCreate(
        "z",
        {
            "dest_path": "out/secret.zip",
            "items": ["data/secret.txt"],
            "src_dir": ".",
            "password": "pw123",
        },
        ctx,
        job_id,
    )
    out = z.run()
    assert Path(out["output"]).exists()
    assert out["password"] is True

    # Wrong password should fail
    u_bad = ZipExtract(
        "u",
        {
            "archives": ["out/secret.zip"],
            "dest_dir": "out/bad",
            "src_dir": ".",
            "password": "wrong",
            "private_zip_folder": False
        },
        ctx,
        job_id,
    )
    with pytest.raises(Exception):
        u_bad.run()

    u = ZipExtract(
        "u2",
        {
            "archives": ["out/secret.zip"],
            "dest_dir": "out/good",
            "src_dir": ".",
            "password": "pw123",
        },
        ctx,
        job_id,
    )
    uout = u.run()
    assert Path(uout["dest_dir"]).exists()
    assert (Path(uout["dest_dir"]) / "out/data/secret.txt").read_text() == "shh"
