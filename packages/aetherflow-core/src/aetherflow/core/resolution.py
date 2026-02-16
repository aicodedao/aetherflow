"""Unified strict template resolution.

This module replaces legacy templating with a minimal, explicit
syntax.

Allowed tokens ONLY:
- {{PATH}}
- {{PATH:DEFAULT}}

Where:
- PATH = IDENT(.IDENT)*
- Spaces are allowed inside braces (e.g. {{  VAR  }})

Everything else MUST fail-fast with ResolverSyntaxError whose message MUST be
exactly:
"Unsupported templating syntax. Use {{VAR}} or {{VAR:DEFAULT}}"
"""

from __future__ import annotations

import copy
import logging
import os
import re
from typing import Any, Mapping, Sequence

from aetherflow.core.exception import ResolverMissingKeyError, ResolverSyntaxError

_UNSUPPORTED_MSG = "Unsupported templating syntax. Use {{VAR}} or {{VAR:DEFAULT}}"
log = logging.getLogger('aetherflow.core.resolution')


def _syntax_error(msg) -> ValueError:
    return ResolverSyntaxError(_UNSUPPORTED_MSG + "\n" + msg)


def _is_identifier(token: str) -> bool:
    if not token:
        return False
    if not (token[0].isalpha() or token[0] == "_"):
        return False
    for ch in token[1:]:
        if not (ch.isalnum() or ch == "_"):
            return False
    return True


def _is_valid_path(path: str) -> bool:
    parts = path.split(".")
    return all(_is_identifier(p) for p in parts)


def _lookup_path(mapping: Mapping[str, Any], path: str) -> tuple[bool, Any]:
    cur: Any = mapping
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return False, None
    return True, cur


def _contains_forbidden_syntax(value: str) -> bool:
    # Hard forbidden patterns.
    needle = "$" + "{"
    if needle in value:
        return True
    if "{%" in value or "%}" in value:
        return True
    if "{#" in value or "#}" in value:
        return True
    if "{}" in value:
        return True
    return False


def render_string(value: str, mapping: dict) -> str:
    """Render a single string using the strict template contract."""
    return _render_string(value, mapping=mapping, strict=True, allowed_roots=None)


def walk_and_render(obj: Any, mapping: dict) -> Any:
    """Deep-walk and render strings in nested dict/list structures.

    Contract:
    - If any dict contains keys config/options/decode, fail-fast.
    - Only strings are templated; other primitives are returned as-is.
    """
    return _walk_and_render(obj, mapping=mapping, strict=True, allowed_roots=None)


def resolve_resource_templates(obj: Any, env_snapshot: Mapping[str, str] | None) -> Any:
    """Phase entrypoint for resource template rendering (still isolated).

    We only expose env as a root: {{env.VAR}} / {{env.VAR:DEFAULT}}
    """
    # Resource templates may only reference env.*
    allowed_roots = {"env"}
    mapping = {"env": dict(env_snapshot or {})}
    return _walk_and_render(obj, mapping=mapping, strict=True, allowed_roots=allowed_roots)


def resolve_flow_meta_templates(obj: Any, env_snapshot: Mapping[str, str] | None) -> Any:
    """Phase entrypoint for flow-meta template rendering (still isolated).

    We only expose env as a root: {{env.VAR}} / {{env.VAR:DEFAULT}}
    """
    # FlowMeta templates may only reference env.*
    allowed_roots = {"env"}
    mapping = {"env": dict(env_snapshot or {})}
    return _walk_and_render(obj, mapping=mapping, strict=True, allowed_roots=allowed_roots)


def resolve_step_templates(obj: Any, runtime_ctx: Mapping[str, Any]) -> Any:
    """Phase entrypoint for step template rendering (still isolated).

    Allowed template roots only:
      env, steps, job, run_id, flow_id, result
    """
    allowed_roots = {"env", "steps", "job", "run_id", "flow_id", "result", "jobs"}
    mapping = dict(runtime_ctx or {})
    return _walk_and_render(obj, mapping=mapping, strict=True, allowed_roots=allowed_roots)


def resolve_resource(resource_dict: Mapping[str, Any], env: Mapping[str, str] | None, set_envs_module: Any) -> dict:
    """Resolve a single resource dict using the unified strict pipeline.

    This function is intentionally isolated (no runtime rewiring yet).
    """
    # 1) env_snapshot = copy(os.environ) OR provided env dict
    env_snapshot: dict[str, str] = dict(env) if env is not None else dict(os.environ)

    # 2) If set_envs_module exists: MUST define expand_env AND decode, else raise immediately
    set_envs = set_envs_module
    if set_envs is not None:
        expand_env = getattr(set_envs, "expand_env", None)
        decode_fn = getattr(set_envs, "decode", None)
        if not callable(expand_env) or not callable(decode_fn):
            raise RuntimeError("set_envs_module must define callable expand_env and decode")

        # 3) env_snapshot = set_envs.expand_env(env_snapshot)
        env_snapshot = dict(expand_env(env_snapshot))

    # Make a deep-ish copy of the resource to avoid mutating the caller.
    resolved: dict[str, Any] = copy.deepcopy(dict(resource_dict))

    # Capture raw config/options before template rendering for decode concatenation checks.
    raw_config = copy.deepcopy(resolved.get("config"))
    raw_options = copy.deepcopy(resolved.get("options"))

    # 4) resolve_resource_templates(config/options) using env_snapshot ONLY
    if "config" in resolved:
        resolved["config"] = resolve_resource_templates(resolved["config"], env_snapshot)
    if "options" in resolved:
        resolved["options"] = resolve_resource_templates(resolved["options"], env_snapshot)

    # 5) Apply decode rules (if any)
    decode_spec = resolved.get("decode")
    decode_requests = _collect_decode_requests(decode_spec)

    if decode_requests:
        # If set_envs missing (or decode missing), warn and leave values unchanged.
        if set_envs is None:
            log.warning(
                "decode requested but set_envs.decode missing; leaving value as-is"
            )
            return resolved

        # Enforce template concatenation rule using raw values (pre-render).
        for section, path in decode_requests:
            raw_root = raw_config if section == "config" else raw_options
            raw_val = _get_by_path(raw_root, path)
            if isinstance(raw_val, str) and ("{{" in raw_val or "}}" in raw_val):
                if not _is_standalone_token(raw_val):
                    raise _syntax_error(f"{raw_root} -> {raw_val}")

        # Perform decode on resolved values (post-render)
        decode_fn = getattr(set_envs, "decode")
        for section, path in decode_requests:
            root_key = section
            if root_key not in resolved:
                continue
            cur_val = _get_by_path(resolved[root_key], path)
            # Only decode leaf strings; other types are left untouched.
            if isinstance(cur_val, str):
                _set_by_path(resolved[root_key], path, decode_fn(cur_val))

    return resolved

# -----------------------------
# Decode helpers (resource phase)
# -----------------------------

#_STANDALONE_TOKEN_RE = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)\s*\}\}$")
_STANDALONE_TOKEN_RE = re.compile(
    r"^\{\{\s*"
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"  # key
    r"(?:\:([^}]*))?"  # optional :default (allow empty)
    r"\s*\}\}$"
)


def _is_standalone_token(value: str) -> bool:
    """True if the string is exactly a single token like {{TOKEN}} (spaces inside ok)."""
    return _STANDALONE_TOKEN_RE.match(value.strip()) is not None


def _collect_decode_requests(decode_spec: Any) -> list[tuple[str, str]]:
    """Return list of (section, path) to decode.

    Supported shapes:
      decode:
        config:
          password: true
          headers:
            Authorization: true

    OR:
      decode:
        config_paths: ["password", "headers.Authorization"]
    """
    if not decode_spec:
        return []

    if not isinstance(decode_spec, Mapping):
        raise _syntax_error(str(decode_spec))

    requests: list[tuple[str, str]] = []

    def walk_bool_map(section: str, node: Any, prefix: str = "") -> None:
        if isinstance(node, Mapping):
            for k, v in node.items():
                if not isinstance(k, str):
                    raise _syntax_error(f"{k} is not string!")
                new_prefix = f"{prefix}.{k}" if prefix else k
                walk_bool_map(section, v, new_prefix)
            return

        if node is True:
            if not prefix:
                raise _syntax_error(f"Node is true, and not prefix {prefix}")
            requests.append((section, prefix))
            return

        if node in (False, None):
            return

        # Any other leaf type is unsupported.
        raise _syntax_error(f"Node unknow. Section {section} Prefix {prefix}")

    # Nested bool-map style
    for section in ("config", "options"):
        if section in decode_spec:
            walk_bool_map(section, decode_spec[section], "")

    # Path list style
    if "config_paths" in decode_spec:
        paths = decode_spec["config_paths"]
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
            raise _syntax_error(f"config_paths {paths}")
        for p in paths:
            if not isinstance(p, str) or not p:
                raise _syntax_error(f"config_paths {paths} {p}")
            requests.append(("config", p))

    if "options_paths" in decode_spec:
        paths = decode_spec["options_paths"]
        if not isinstance(paths, Sequence) or isinstance(paths, (str, bytes)):
            raise _syntax_error(f"options_paths {paths}")
        for p in paths:
            if not isinstance(p, str) or not p:
                raise _syntax_error(f"options_paths {paths} {p}")
            requests.append(("options", p))

    # De-dupe while preserving order
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str]] = []
    for item in requests:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _get_by_path(root: Any, path: str) -> Any:
    if root is None:
        return None
    cur = root
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _set_by_path(root: Any, path: str, value: Any) -> None:
    if not isinstance(root, Mapping):
        return
    cur: Any = root
    parts = path.split(".")
    for part in parts[:-1]:
        if isinstance(cur, Mapping) and part in cur and isinstance(cur[part], Mapping):
            cur = cur[part]
        elif isinstance(cur, Mapping):
            cur[part] = {}
            cur = cur[part]
        else:
            return
    last = parts[-1]
    if isinstance(cur, Mapping):
        cur[last] = value

def _render_string(
    value: str,
    *,
    mapping: Mapping[str, Any],
    strict: bool,
    allowed_roots: set[str] | None,
) -> str:
    if not isinstance(value, str):
        raise TypeError("render_string expects a string value")

    # Any forbidden syntax anywhere should hard fail.
    if _contains_forbidden_syntax(value):
        raise _syntax_error(f"_contains_forbidden_syntax {value}")

    # Fast path: nothing to do.
    if "{{" not in value and "}}" not in value:
        return value

    out: list[str] = []
    i = 0
    n = len(value)

    while i < n:
        start = value.find("{{", i)
        if start == -1:
            out.append(value[i:])
            break

        # If we see a closing braces before the next opening, it's malformed.
        premature_close = value.find("}}", i, start)
        if premature_close != -1:
            raise _syntax_error(f"premature_close <> -1 {value}")

        out.append(value[i:start])
        end = value.find("}}", start + 2)
        if end == -1:
            raise _syntax_error(f"missing_close <> -1 {value}")

        inner = value[start + 2 : end]
        token = inner.strip()

        # Empty token or nested braces are not allowed.
        if not token or "{" in token or "}" in token:
            raise _syntax_error(f"Empty token or nested braces are not allowed.")

        # Split PATH[:DEFAULT] at the first colon.
        if ":" in token:
            path, default = token.split(":", 1)
            path = path.strip()
            default = default  # default keeps exact spacing after colon
        else:
            path, default = token.strip(), None

        if not _is_valid_path(path):
            raise _syntax_error(f"_is_valid_path False {path}")

        if allowed_roots is not None:
            root = path.split(".", 1)[0]
            if root not in allowed_roots:
                raise _syntax_error(f"allowed_roots {root} {path} {allowed_roots}")

        found, resolved = _lookup_path(mapping, path)
        # Empty string counts as missing per contract.
        if not found or resolved == "":
            if default is not None:
                out.append(str(default))
            else:
                if strict:
                    raise ResolverMissingKeyError(path)
                out.append("")
        else:
            out.append(str(resolved))

        i = end + 2

    rendered = "".join(out)

    # Contract: any legacy expansion at runtime is forbidden (even if introduced indirectly)
    if _contains_forbidden_syntax(rendered):
        raise _syntax_error(f"_contains_forbidden_syntax {rendered}")

    return rendered


def _render_string_or_typed(
        value: str,
        *,
        mapping: Mapping[str, Any],
        strict: bool,
        allowed_roots: set[str] | None,
) -> Any:
    # forbidden syntax check stays the same
    if _contains_forbidden_syntax(value):
        raise _syntax_error(f"_contains_forbidden_syntax {value}")

    # fast path
    if "{{" not in value and "}}" not in value:
        return value

    # --- NEW: standalone token returns typed ---
    m = _STANDALONE_TOKEN_RE.match(value)
    if m:
        path = m.group(1)
        default = m.group(2)  # None if no ':', "" if ':}}'

        if not _is_valid_path(path):
            raise _syntax_error(f"_is_valid_path False {path}")

        if allowed_roots is not None:
            root = path.split(".", 1)[0]
            if root not in allowed_roots:
                raise _syntax_error(f"allowed_roots {root} {path} {allowed_roots}")

        found, resolved = _lookup_path(mapping, path)

        # Contract: empty string counts as missing
        if (not found) or resolved == "":
            if default is not None:
                return default  # keep as string, can be ""
            if strict:
                raise ResolverMissingKeyError(path)
            return ""  # keep behavior: missing -> empty string
        else:
            return resolved  # <-- IMPORTANT: no str()

    # --- inline/multi-token: must return string ---
    return _render_string(
        value,
        mapping=mapping,
        strict=strict,
        allowed_roots=allowed_roots,
    )


def _walk_and_render(
    obj: Any,
    *,
    mapping: Mapping[str, Any],
    strict: bool,
    allowed_roots: set[str] | None,
) -> Any:
    if isinstance(obj, str):
        return _render_string_or_typed(obj, mapping=mapping, strict=strict, allowed_roots=allowed_roots)

    if isinstance(obj, Mapping):
        return {
            k: _walk_and_render(v, mapping=mapping, strict=strict, allowed_roots=allowed_roots)
            for k, v in obj.items()
        }

    if isinstance(obj, list):
        return [_walk_and_render(v, mapping=mapping, strict=strict, allowed_roots=allowed_roots) for v in obj]

    if isinstance(obj, tuple):
        return tuple(_walk_and_render(v, mapping=mapping, strict=strict, allowed_roots=allowed_roots) for v in obj)

    # int/bool/float/None etc
    return obj