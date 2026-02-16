"""AetherFlow strict architecture guard.

This module enforces two hard rules at import-time:

1) All customized exceptions MUST be defined in `aetherflow/exception.py`.
2) All Spec classes MUST be defined in `aetherflow/spec.py`.

If someone defines a violating class elsewhere, we raise RuntimeError with an actionable
message pointing to the exact file + class name.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Iterable


_EXCLUDED_DIRS = {
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "build",
    "dist",
    ".eggs",
    ".git",
}
_EXCLUDED_TOPLEVEL = {"tests", "test", "demo", "docs"}


def _iter_python_files(package_root: Path) -> Iterable[Path]:
    for path in package_root.rglob("*.py"):
        parts = set(path.parts)
        if parts & _EXCLUDED_DIRS:
            continue
        # ignore tests/demo/docs anywhere in the path
        if parts & _EXCLUDED_TOPLEVEL:
            continue
        yield path


def _base_id(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        cur: ast.expr = node
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    if isinstance(node, ast.Subscript):
        return _base_id(node.value)
    return None


def _is_exception_subclass(cls: ast.ClassDef) -> bool:
    """Heuristic: if any base looks like an exception type, treat as exception subclass.

    We intentionally keep this strict: inheriting ValueError/KeyError/etc still counts.
    """
    for base in cls.bases:
        bid = _base_id(base)
        if not bid:
            continue
        last = bid.split(".")[-1]
        if last in {"BaseException", "Exception"}:
            return True
        if last.endswith("Error") or last.endswith("Exception"):
            return True
    return False


def assert_architecture() -> None:
    """Scan the aetherflow source tree and raise if strict rules are violated.

    Disable by setting env var AETHERFLOW_STRICT_ARCH=0.
    """
    if os.getenv("AETHERFLOW_STRICT_ARCH", "1") == "0":
        return

    package_root = Path(__file__).resolve().parent
    exception_file = (package_root / "exception.py").resolve()
    spec_file = (package_root / "spec.py").resolve()

    exc_violations: list[tuple[str, Path]] = []
    spec_violations: list[tuple[str, Path]] = []

    for path in _iter_python_files(package_root):
        # single sources of truth are allowed
        if path.resolve() in {exception_file, spec_file}:
            continue

        try:
            src = path.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(path))
        except (OSError, UnicodeDecodeError, SyntaxError):
            # If source can't be parsed, treat it as a real error to surface early.
            raise RuntimeError(
                f"[AetherFlow strict-arch] Cannot parse source file: {path}"
            )

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            # RULE #1: exception subclasses outside exception.py
            if _is_exception_subclass(node):
                exc_violations.append((node.name, path))

            # RULE #2: Spec classes outside spec.py
            if node.name.endswith("Spec"):
                spec_violations.append((node.name, path))

    if not exc_violations and not spec_violations:
        return

    lines: list[str] = ["AetherFlow strict architecture check failed:"]
    if exc_violations:
        lines.append("")
        lines.append("RULE #1 — CUSTOMIZED EXCEPTIONS:")
        for cls, path in sorted(exc_violations, key=lambda x: (str(x[1]), x[0])):
            lines.append(f"  - {cls} defined in {path}")
        lines.append("Fix: move these exception classes into aetherflow/core/exception.py and import from aetherflow.core.exception.")

    if spec_violations:
        lines.append("")
        lines.append("RULE #2 — SPECS:")
        for cls, path in sorted(spec_violations, key=lambda x: (str(x[1]), x[0])):
            lines.append(f"  - {cls} defined in {path}")
        lines.append("Fix: move these Spec classes into aetherflow/core/spec.py and import from aetherflow.core.spec.")

    raise RuntimeError("\n".join(lines))
