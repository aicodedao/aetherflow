"""Secrets hook loader.

Goal:
- Allow users to define a dynamic secret decoder (like set_envs.py)
- DO NOT mutate os.environ (safe for parallel flow runs)

Config:
- AETHERFLOW_SECRETS_MODULE: import module that exposes decode(value)->str and expand_env(env)->dict
- AETHERFLOW_SECRETS_PATH: python file path that exposes decode(...) and expand_env(...)

Behavior:
- aetherflow takes an env snapshot: env = dict(os.environ)
- if expand_env exists: env = expand_env(env) (returns new dict)
- when building resource config/options from env mapping:
    if key is marked decode=true, aetherflow calls decode(value) ALWAYS (no ENC wrapper required)
"""

from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional


DecodeFn = Callable[[str], str]
ExpandFn = Callable[[dict], dict]


@dataclass
class SecretsProvider:
    decode: DecodeFn
    expand_env: Optional[ExpandFn] = None


def _enforce_set_envs_contract(m: object, *, origin: str) -> None:
    """Enforce the public contract for the secrets hook.

    Aetherflow intentionally only uses two public functions:
      - decode(value: str) -> str
      - expand_env(env: dict) -> dict (optional)

    Anything else should be private (prefixed with '_') or non-callable constants.
    This keeps user hooks boring/predictable and prevents "random helper" sprawl.
    """

    public_callables: list[str] = []
    for name in dir(m):
        if name.startswith("_"):
            continue
        if name in {"decode", "expand_env"}:
            continue
        try:
            attr = getattr(m, name)
        except Exception:
            continue
        if callable(attr):
            public_callables.append(name)

    if public_callables:
        raise TypeError(
            f"Secrets hook {origin} defines unsupported public callables: {sorted(public_callables)}. "
            "Only 'decode' and optional 'expand_env' are allowed (helpers must be private, e.g. _helper())."
        )


def _load_from_module(mod_name: str) -> SecretsProvider:
    m = importlib.import_module(mod_name)
    _enforce_set_envs_contract(m, origin=f"module:{mod_name}")
    dec = getattr(m, "decode", None)
    if not callable(dec):
        raise TypeError("Secrets module must define callable decode(value: str) -> str")
    exp = getattr(m, "expand_env", None)
    return SecretsProvider(decode=dec, expand_env=exp if callable(exp) else None)


def _load_from_path(path: str) -> SecretsProvider:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"Secrets path not found: {p}")

    mod_name = f"aetherflow_secrets_{p.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, p)
    if not spec or not spec.loader:
        raise RuntimeError(f"Unable to load secrets module from path: {p}")

    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)

    _enforce_set_envs_contract(m, origin=f"path:{p}")

    dec = getattr(m, "decode", None)
    if not callable(dec):
        raise TypeError("Secrets file must define callable decode(value: str) -> str")
    exp = getattr(m, "expand_env", None)
    return SecretsProvider(decode=dec, expand_env=exp if callable(exp) else None)


def load_secrets_provider(*, secrets_module: str | None, secrets_path: str | None) -> SecretsProvider | None:
    if secrets_module:
        return _load_from_module(secrets_module)
    if secrets_path:
        return _load_from_path(secrets_path)
    return None
