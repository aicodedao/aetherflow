from __future__ import annotations

import importlib
import logging
import sys
from pathlib import Path
from importlib.metadata import entry_points

log = logging.getLogger('aetherflow.core.plugins')


def load_plugins_from_entrypoints(group: str = "aetherflow.plugins", *, strict: bool = True) -> None:
    try:
        eps = entry_points().select(group=group)
    except Exception as e:
        if strict:
            raise RuntimeError(f"Failed reading entry points for group={group}: {e}") from e
        log.warning("Failed reading entry points; continuing", exc_info=True)
        eps = []
    for ep in eps:
        try:
            obj = ep.load()
            if callable(obj):
                obj()
            elif hasattr(obj, "register"):
                obj.register()
        except Exception as e:
            if strict:
                raise RuntimeError(f"Failed loading entry point plugin {ep.name}: {e}") from e
            log.warning(f"Failed loading entry point plugin {ep.name}; continuing", exc_info=True)


def _iter_py_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if p.name.startswith("_"):
            continue
        yield p


def load_plugins_from_paths(paths: list[str], *, strict: bool = True) -> None:
    for raw in paths:
        if not raw:
            continue
        root = Path(raw).expanduser().resolve()
        if not root.exists():
            if strict:
                raise FileNotFoundError(f"Plugin path not found: {root}")
            continue
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        for py in _iter_py_files(root):
            try:
                mod_name = "aetherflow_user_plugin_" + "_".join(py.with_suffix("").parts[-4:])
                spec = importlib.util.spec_from_file_location(mod_name, py)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
            except Exception as e:
                if strict:
                    raise RuntimeError(f"Failed loading plugin file: {py}: {e}") from e
                log.warning(f"Failed loading plugin file: {py}; continuing", exc_info=True)


def load_all_plugins(*, settings) -> None:
    load_plugins_from_entrypoints(strict=settings.plugin_strict)
    load_plugins_from_paths(settings.plugin_paths, strict=settings.plugin_strict)
