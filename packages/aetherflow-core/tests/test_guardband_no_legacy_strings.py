from __future__ import annotations

from pathlib import Path


def test_repo_contains_no_legacy_templating_strings():
    """Guardband: fail CI if forbidden legacy strings are present.

    This is intentionally strict and fast. It scans tracked repo files while
    excluding common build/cache directories.
    """

    repo_root = Path(__file__).resolve().parents[3]

    # Exclude dirs where scanning is noisy/slow or irrelevant.
    excluded = {
        ".git",
        ".github",
        "venv",
        ".venv",
        "dist",
        "build",
        "node_modules",
        ".pytest_cache",
        "__pycache__",
        ".ruff_cache",
        ".mypy_cache",
        ".coverage",
        "htmlcov",
        "coverage",
    }

    # Build needles without embedding the forbidden literals in this file.
    forbidden = [
        "$" + "{",
        "config" + "_env",
        "options" + "_env",
        "decode" + "_env",
        "import " + "jinja2",
    ]

    offenders: list[str] = []

    for p in repo_root.rglob("*"):
        if any(part in excluded for part in p.parts):
            continue
        if not p.is_file():
            continue
        # Release artifacts at repo root may contain literal legacy strings in instructions.
        if p.name in {"MIGRATION_SUMMARY.txt", "POST_MIGRATION_CHECKS.txt"}:
            continue
        # Skip binaries
        try:
            data = p.read_text(encoding="utf-8")
        except Exception:
            continue
        for needle in forbidden:
            if needle in data:
                offenders.append(f"{p.relative_to(repo_root)}: {needle}")

    assert offenders == [], "Forbidden legacy strings found:\n" + "\n".join(offenders)
