import os
from pathlib import Path

import pytest


def _iter_text_files(repo_root: Path):
    skip_dirs = {
        ".git",
        ".github",
        "venv",
        ".venv",
        "dist",
        "build",
        ".pytest_cache",
        "node_modules",
        "__pycache__",
        ".ruff_cache",
        ".mypy_cache",
        ".coverage",
        "htmlcov",
        ".tox",
    }
    text_exts = {".md", ".rst", ".txt", ".yml", ".yaml"}

    for p in repo_root.rglob("*"):
        if p.is_dir():
            continue
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.suffix.lower() not in text_exts:
            continue
        yield p


def _is_doc_or_readme(p: Path) -> bool:
    s = str(p).replace("\\", "/")
    name = p.name.lower()
    if "/docs/" in s:
        return True
    if "readme" in name:
        return True
    return False


@pytest.mark.parametrize("needle", [
    "$" + "{",
    "config" + "_" + "env",
    "options" + "_" + "env",
    "decode" + "_" + "env",
    "import " + "jinja2",
])
def test_docs_no_legacy_strings(needle: str):
    # Repo root (two levels above packages/aetherflow-core)
    core_root = Path(__file__).resolve().parents[2]  # packages/aetherflow-core
    repo_root = core_root.parent.parent  # repo root

    hits = []
    for p in _iter_text_files(repo_root):
        s = str(p).replace("\\", "/")
        # Only scan docs + readmes, and never scan tests.
        if "/tests/" in s:
            continue
        if not _is_doc_or_readme(p):
            continue

        txt = p.read_text(encoding="utf-8", errors="ignore")
        if needle in txt:
            hits.append(str(p))

    assert not hits, f"Found legacy token '{needle}' in docs/readmes: {hits}"
