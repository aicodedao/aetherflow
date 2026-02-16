from __future__ import annotations


def require(spec: str):
    """
    spec:
      - "a.b.c" -> module
                import a.b.c -> require("a.b.c")
      - "a.b:c" -> attribute c from module a.b
            from a.b import c -> require("a.b:c")
    """
    import importlib
    try:
        if ":" in spec:
            module_name, attr = spec.split(":", 1)
            return require_attr(module_name=module_name, attr_name=attr)
        else:
            return importlib.import_module(spec)
    except Exception as e:
        raise RuntimeError(
            f"Optional dependency missing: Module {spec}. "
            f"Install it to use this connector/step."
        ) from e


def require_attr(module_name: str, attr_name: str):
    """
    spec:
        from a.b import c -> require("a.b", "c")
    """
    import importlib
    try:
        mod = importlib.import_module(module_name)
        return getattr(mod, attr_name)
    except Exception as e:
        raise RuntimeError(
            f"Optional dependency missing: Module {module_name} Attribute {attr_name}. "
            f"Install it to use this connector/step."
        ) from e
