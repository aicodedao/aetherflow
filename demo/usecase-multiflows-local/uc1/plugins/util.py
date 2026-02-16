from __future__ import annotations

def require(module_name: str):
    try:
        return __import__(module_name)
    except Exception as e:
        raise RuntimeError(
            f"Optional dependency missing: {module_name}. Install it to use this connector/step."
        ) from e
