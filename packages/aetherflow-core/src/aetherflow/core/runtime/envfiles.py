from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


from aetherflow.core.spec import EnvFileSpec


def _read_dotenv(p: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        # strip simple quotes
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def _read_json(p: Path) -> Dict[str, str]:
    obj = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise TypeError("json env file must be a JSON object")
    out: Dict[str, str] = {}
    for k, v in obj.items():
        if v is None:
            continue
        out[str(k)] = str(v) if not isinstance(v, (dict, list)) else json.dumps(v, ensure_ascii=False)
    return out


def _read_dir(p: Path) -> Dict[str, str]:
    if not p.is_dir():
        raise NotADirectoryError(str(p))
    out: Dict[str, str] = {}
    for fp in sorted(p.iterdir()):
        if fp.is_file():
            out[fp.name] = fp.read_text(encoding="utf-8").rstrip("\n")
    return out


def load_env_files(specs: Iterable[EnvFileSpec], *, base_dir: Optional[Path] = None) -> Dict[str, str]:
    """Load env vars for a list of EnvFileSpec.

    Later specs override earlier ones (deterministic).
    """
    merged: Dict[str, str] = {}
    for s in specs:
        t = (s.type or "").strip().lower()
        path = Path(s.path)
        if base_dir and not path.is_absolute():
            path = (base_dir / path)

        if not path.exists():
            if s.optional:
                continue
            raise FileNotFoundError(str(path))

        if t == "dotenv":
            data = _read_dotenv(path)
        elif t == "json":
            data = _read_json(path)
        elif t in ("dir", "directory", "dir-of-files"):
            data = _read_dir(path)
        else:
            raise ValueError(f"Unsupported env_files type: {s.type}")

        if s.prefix:
            data = {f"{s.prefix}{k}": v for k, v in data.items()}

        merged.update({str(k): str(v) for k, v in data.items()})
    return merged


def parse_env_files_json(raw: str) -> List[EnvFileSpec]:
    """Parse a JSON string into env file specs.

    Expected format:
      [ {"type": "dotenv", "path": "env/common.env", "optional": true, "prefix": ""}, ... ]
    """
    arr = json.loads(raw)
    if not isinstance(arr, list):
        raise TypeError("AETHERFLOW_ENV_FILES_JSON must be a JSON list")
    out: List[EnvFileSpec] = []
    for it in arr:
        if not isinstance(it, dict):
            raise TypeError("env file spec must be an object")
        out.append(
            EnvFileSpec(
                type=str(it.get("type") or ""),
                path=str(it.get("path") or ""),
                optional=bool(it.get("optional", False)),
                prefix=str(it.get("prefix") or ""),
            )
        )
    return out


def parse_env_files_manifest(obj: Any) -> List[EnvFileSpec]:
    """Parse manifest YAML env.files section into specs."""
    files = (obj or {}).get("env_files") if isinstance(obj, dict) else None
    if not files:
        return []
    if not isinstance(files, list):
        raise TypeError("manifest env.files must be a list")
    out: List[EnvFileSpec] = []
    for it in files:
        if not isinstance(it, dict):
            raise TypeError("manifest env.files entry must be a dict")
        out.append(
            EnvFileSpec(
                type=str(it.get("type") or it.get("format") or "dotenv"),
                path=str(it.get("path") or ""),
                optional=bool(it.get("optional", False)),
                prefix=str(it.get("prefix") or ""),
            )
        )
    return out
