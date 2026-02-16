from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pytest
import yaml

from aetherflow.core.spec import FlowSpec


def _repo_root() -> Path:
    """Return monorepo root (the folder that contains 'docs/' and 'demo/')."""
    here = Path(__file__).resolve()
    # .../aetherflow/packages/aetherflow-core/tests/<thisfile>
    # -> go up 4 to .../aetherflow
    for _ in range(6):
        if (here / "docs").is_dir() and (here / "demo").is_dir():
            return here
        here = here.parent
    raise RuntimeError("Could not locate repo root containing docs/ and demo/")


def _is_flow_doc(d: Any) -> bool:
    return isinstance(d, dict) and "version" in d and "flow" in d and "jobs" in d


@dataclass(frozen=True)
class YamlExample:
    origin: str
    text: str


def _iter_demo_flow_files(root: Path) -> Iterable[Path]:
    # Canonical demo flows live here.
    for p in sorted((root / "demo").glob("**/flows/*.y*ml")):
        yield p


_FENCE_RE = re.compile(
    r"```(?:yaml|yml)\s*\n(?P<body>.*?)\n```",
    flags=re.IGNORECASE | re.DOTALL,
)


def _iter_doc_flow_examples(root: Path) -> Iterable[YamlExample]:
    docs_dir = root / "docs"
    if not docs_dir.is_dir():
        return
    for md in sorted(docs_dir.glob("**/*.md")):
        text = md.read_text(encoding="utf-8")
        for idx, m in enumerate(_FENCE_RE.finditer(text), start=1):
            body = m.group("body").strip()
            # Only validate blocks that look like a Flow YAML (avoid manifest/scheduler snippets).
            if "flow:" not in body or "jobs:" not in body or "version:" not in body:
                continue
            yield YamlExample(origin=f"{md.relative_to(root)}#yaml_block_{idx}", text=body)


@pytest.mark.contract
def test_demo_flow_yamls_validate_against_flowspec() -> None:
    root = _repo_root()
    failures: list[str] = []

    for fp in _iter_demo_flow_files(root):
        raw = fp.read_text(encoding="utf-8")
        try:
            data = yaml.safe_load(raw)
        except Exception as e:  # pragma: no cover
            failures.append(f"YAML parse failed: {fp.relative_to(root)} :: {e}")
            continue

        if not _is_flow_doc(data):
            failures.append(
                f"Not a FlowSpec YAML (missing version/flow/jobs): {fp.relative_to(root)}"
            )
            continue

        try:
            FlowSpec.model_validate(data)
        except Exception as e:
            failures.append(f"FlowSpec validation failed: {fp.relative_to(root)} :: {e}")

    assert not failures, "\n".join(failures)


@pytest.mark.contract
def test_docs_yaml_flow_examples_validate_against_flowspec() -> None:
    root = _repo_root()
    failures: list[str] = []

    for ex in _iter_doc_flow_examples(root):
        try:
            data = yaml.safe_load(ex.text)
        except Exception as e:
            failures.append(f"YAML parse failed: {ex.origin} :: {e}")
            continue

        # Some blocks might be partials; only validate full Flow docs.
        if not _is_flow_doc(data):
            continue

        try:
            FlowSpec.model_validate(data)
        except Exception as e:
            failures.append(f"FlowSpec validation failed: {ex.origin} :: {e}")

    assert not failures, "\n".join(failures)
