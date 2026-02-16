from __future__ import annotations
from typing import Dict, Type

_STEP_REGISTRY: Dict[str, Type] = {}


def register_step(name: str):
    def deco(cls):
        _STEP_REGISTRY[name] = cls
        return cls
    return deco


def get_step(name: str):
    if name not in _STEP_REGISTRY:
        raise KeyError(f"Unknown step type: {name}. Loaded: {sorted(_STEP_REGISTRY.keys())}")
    return _STEP_REGISTRY[name]


def list_steps() -> list[str]:
    return sorted(_STEP_REGISTRY.keys())
