from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional
import logging

import yaml
# Ensure built-ins register even when validation is called standalone.
from aetherflow.core.runtime import _bootstrap  # noqa: F401
from aetherflow.core.diagnostics.env_snapshot import build_env_snapshot
from aetherflow.core.plugins import load_all_plugins
from aetherflow.core.registry.steps import list_steps
from aetherflow.core.runtime.settings import Settings, load_settings
from aetherflow.core.spec import FlowSpec, FlowMetaSpec
from aetherflow.core.exception import ResolverMissingKeyError, ResolverSyntaxError, SpecError
from aetherflow.core.resolution import render_string, resolve_resource_templates, resolve_flow_meta_templates, resolve_step_templates
from pydantic import ValidationError

log = logging.getLogger('aetherflow.core.validation')


@dataclass(frozen=True)
class FlowValidationIssue:
    code: str
    loc: str
    msg: str

    def as_dict(self) -> dict:
        return {"code": self.code, "loc": self.loc, "msg": self.msg}


@dataclass(frozen=True)
class ScanResult:
    """Shared scanner output used by both validation and diagnostics."""

    missing_env_keys: set[str]
    syntax_errors: list[str]
    unknown_root_errors: list[str]
    errors: list[FlowValidationIssue]
    warnings: list[FlowValidationIssue]


_STEP_ALLOWED_ROOTS = {"env", "steps", "job", "run_id", "flow_id", "result", "jobs"}


def _extract_template_roots(s: str) -> set[str]:
    """Best-effort extraction of template roots from a string.

    Only supports the strict contract tokens, and is used solely for better
    diagnostics grouping (unknown root vs generic syntax).
    """

    import re

    roots: set[str] = set()
    # match {{ ... }} blocks, capture inside
    for m in re.finditer(r"\{\{(.*?)\}\}", s):
        inner = (m.group(1) or "").strip()
        if not inner:
            continue
        # split default (:) and path (.): root is first ident
        head = inner.split(":", 1)[0].strip()
        root = head.split(".", 1)[0].strip()
        if root:
            roots.add(root)
    return roots


def _is_standalone_token(s: str) -> bool:
    import re

    return bool(re.fullmatch(r"\s*\{\{\s*[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?::[^}]*)?\s*\}\}\s*", s))

def _get_by_path(obj: Any, path: str) -> Any:
    cur: Any = obj
    if not path:
        return None
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _collect_decode_requests(decode_spec: Any) -> list[tuple[str, str]]:
    """Collect decode requests in the same supported shapes as runtime."""
    if not decode_spec:
        return []
    if not isinstance(decode_spec, dict):
        return []
    reqs: list[tuple[str, str]] = []

    def walk_bool_map(section: str, node: Any, prefix: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if not isinstance(k, str):
                    return
                new_prefix = f"{prefix}.{k}" if prefix else k
                walk_bool_map(section, v, new_prefix)
            return
        if node is True:
            if prefix:
                reqs.append((section, prefix))
            return
        # False/None: ignore; other leaves ignored here (schema will catch)

    for section in ("config", "options"):
        if section in decode_spec:
            walk_bool_map(section, decode_spec.get(section), "")

    for key, section in (("config_paths", "config"), ("options_paths", "options")):
        if key in decode_spec:
            paths = decode_spec.get(key)
            if isinstance(paths, list):
                for p in paths:
                    if isinstance(p, str) and p:
                        reqs.append((section, p))

    return reqs


def scan_profiles_templates(
    profiles_obj: Any,
    *,
    env_snapshot: dict[str, str],
    strict_env: bool,
) -> ScanResult:
    """Scan profiles data (resource semantics: env.* only)."""

    missing_env_keys: set[str] = set()
    syntax_errors: list[str] = []
    unknown_root_errors: list[str] = []
    errors: list[FlowValidationIssue] = []
    warnings: list[FlowValidationIssue] = []

    if not isinstance(profiles_obj, dict):
        return ScanResult(missing_env_keys, syntax_errors, unknown_root_errors, errors, warnings)

    def _add_missing(loc: str, key: str) -> None:
        missing_env_keys.add(key)
        iss = FlowValidationIssue(code="semantic:missing_env", loc=loc, msg=f"Missing env {key}")
        (errors if strict_env else warnings).append(iss)

    for pname, pobj in profiles_obj.items():
        if not isinstance(pobj, dict):
            continue
        for section in ("config", "options", "decode"):
            if section not in pobj:
                continue
            base_loc = f"profiles.{pname}.{section}"
            subtree = pobj.get(section)
            for loc, s in _iter_strings(subtree, base_loc=""):
                full_loc = f"{base_loc}.{loc}" if loc else base_loc
                try:
                    # Profiles are resource-templated: env.* only
                    render_string(s, mapping={"env": dict(env_snapshot)})
                except ResolverMissingKeyError as e:
                    key = str(e.args[0]) if e.args else str(e)
                    if key == "env" or key.startswith("env."):
                        _add_missing(full_loc, key)
                except ResolverSyntaxError as e:
                    syntax_errors.append(str(e))
                    errors.append(FlowValidationIssue(code="template:syntax", loc=full_loc, msg=str(e)))
            # Decode: if it contains templates, must be standalone token
            if section == "decode":
                for loc, s in _iter_strings(subtree, base_loc=""):
                    if "{{" in s:
                        if not _is_standalone_token(s):
                            msg = "Unsupported templating syntax. Use {{VAR}} or {{VAR:DEFAULT}}"
                            syntax_errors.append(msg)
                            errors.append(FlowValidationIssue(code="template:syntax", loc=f"{base_loc}.{loc}" if loc else base_loc, msg=msg))

    return ScanResult(missing_env_keys, syntax_errors, unknown_root_errors, errors, warnings)


def scan_runtime_templates(
    flow_spec: FlowSpec,
    env_snapshot: dict[str, str],
    *,
    strict_env: bool,
) -> ScanResult:
    """Scan only runtime-templated fields for template syntax and env-missing.

    - Syntax is enforced exactly per the resolver contract.
    - Env strict only checks missing keys rooted at env.*.
    - Unknown roots are flagged only for step/job templating scopes.
    """

    missing_env_keys: set[str] = set()
    syntax_errors: list[str] = []
    unknown_root_errors: list[str] = []
    errors: list[FlowValidationIssue] = []
    warnings: list[FlowValidationIssue] = []

    step_ctx = {
        "env": dict(env_snapshot),
        "steps": {},
        "job": {},
        "run_id": "RUN_ID",
        "flow_id": "FLOW_ID",
        "result": {},
    }

    def _add_missing(loc: str, key: str) -> None:
        missing_env_keys.add(key)
        iss = FlowValidationIssue(code="semantic:missing_env", loc=loc, msg=f"Missing env {key}")
        (errors if strict_env else warnings).append(iss)

    # Resources: config/options/decode (resource semantics: env.* only)
    for rname, r in (flow_spec.resources or {}).items():
        for section in ("config", "options"):
            subtree = getattr(r, section)
            loc_prefix = f"resources.{rname}.{section}"
            try:
                resolve_resource_templates(subtree, env_snapshot=dict(env_snapshot))
            except ResolverMissingKeyError as e:
                key = str(e.args[0]) if e.args else str(e)
                if key == "env" or key.startswith("env."):
                    _add_missing(loc_prefix, key)
            except ResolverSyntaxError as e:
                syntax_errors.append(str(e))
                errors.append(FlowValidationIssue(code="template:syntax", loc=loc_prefix, msg=str(e)))
        # Decode concat rule for resources: any templated value that will be decoded must be a standalone token.
        decode_requests = _collect_decode_requests(getattr(r, "decode", None))
        if decode_requests:
            raw_config = getattr(r, "config", None) or {}
            raw_options = getattr(r, "options", None) or {}
            for sec, path in decode_requests:
                raw_root = raw_config if sec == "config" else raw_options
                raw_val = _get_by_path(raw_root, path)
                if isinstance(raw_val, str) and ("{{" in raw_val or "}}" in raw_val):
                    if not _is_standalone_token(raw_val):
                        msg = "Decode target must be a standalone template token like '{{TOKEN}}' (no prefix/suffix)."
                        syntax_errors.append(msg)
                        errors.append(
                            FlowValidationIssue(
                                code="template:syntax",
                                loc=f"resources.{rname}.{sec}.{path}",
                                msg=msg,
                            )
                        )

        # Decode: validate standalone token constraint when templates are present
        dec = r.decode or {}
        dec_loc = f"resources.{rname}.decode"
        for loc, s in _iter_strings(dec, base_loc=""):
            full_loc = f"{dec_loc}.{loc}" if loc else dec_loc
            if "{{" in s:
                if not _is_standalone_token(s):
                    msg = "Unsupported templating syntax. Use {{VAR}} or {{VAR:DEFAULT}}"
                    syntax_errors.append(msg)
                    errors.append(FlowValidationIssue(code="template:syntax", loc=full_loc, msg=msg))
                else:
                    try:
                        render_string(s, mapping={"env": dict(env_snapshot)})
                    except ResolverMissingKeyError as e:
                        key = str(e.args[0]) if e.args else str(e)
                        if key == "env" or key.startswith("env."):
                            _add_missing(full_loc, key)
                    except ResolverSyntaxError as e:
                        syntax_errors.append(str(e))
                        errors.append(FlowValidationIssue(code="template:syntax", loc=full_loc, msg=str(e)))

    # FlowMeta: resolver
    try:
        resolve_flow_meta_templates(flow_spec.flow.model_dump(), env_snapshot=dict(env_snapshot))
    except ResolverMissingKeyError as e:
        key = str(e.args[0]) if e.args else str(e)
        if key == "env" or key.startswith("env."):
            _add_missing("flow", key)
    except ResolverSyntaxError as e:
        syntax_errors.append(str(e))
        errors.append(FlowValidationIssue(code="template:syntax", loc="flow", msg=str(e)))

    # Steps: inputs/outputs (step semantics: allowed roots only)
    for j_i, job in enumerate(flow_spec.jobs or []):
        for s_i, step in enumerate(job.steps or []):
            for section in ("inputs", "outputs"):
                subtree = getattr(step, section) or {}
                loc_prefix = f"jobs[{j_i}].steps[{s_i}].{section}"

                # Pre-check for unknown roots (for better error grouping)
                for loc, s in _iter_strings(subtree, base_loc=""):
                    for root in _extract_template_roots(s):
                        if root and root not in _STEP_ALLOWED_ROOTS:
                            unknown_root_errors.append(root)
                            errors.append(
                                FlowValidationIssue(
                                    code="template:unknown_root",
                                    loc=f"{loc_prefix}.{loc}" if loc else loc_prefix,
                                    msg=f"Unknown template root: {root}",
                                )
                            )
                            # keep going; resolver will also flag syntax in strict contract

                try:
                    resolve_step_templates(subtree, runtime_ctx=step_ctx)
                except ResolverMissingKeyError as e:
                    key = str(e.args[0]) if e.args else str(e)
                    if key == "env" or key.startswith("env."):
                        _add_missing(loc_prefix, key)
                except ResolverSyntaxError as e:
                    syntax_errors.append(str(e))
                    errors.append(FlowValidationIssue(code="template:syntax", loc=loc_prefix, msg=str(e)))

    return ScanResult(missing_env_keys, syntax_errors, unknown_root_errors, errors, warnings)


def _validate_external_process(step_inputs: dict) -> list[FlowValidationIssue]:
    """Extra semantic checks for the built-in external.process step.

    These catch common misconfigurations early (before running anything).
    """
    issues: list[FlowValidationIssue] = []
    # command required
    if "command" not in step_inputs:
        issues.append(
            FlowValidationIssue(
                code="semantic:external_process_missing_command",
                loc="inputs.command",
                msg="external.process requires inputs.command",
            )
        )
        return issues
    cmd = step_inputs.get("command")
    if not isinstance(cmd, (str, list)):
        issues.append(
            FlowValidationIssue(
                code="semantic:external_process_command_type",
                loc="inputs.command",
                msg="external.process inputs.command must be a string or list",
            )
        )

    # log modes sanity
    log_cfg = step_inputs.get("log") or {}
    if isinstance(log_cfg, dict):
        for key in ("stdout", "stderr"):
            mode = (log_cfg.get(key) or "inherit")
            if mode not in {"inherit", "capture", "file", "discard"}:
                issues.append(
                    FlowValidationIssue(
                        code="semantic:external_process_log_mode",
                        loc=f"inputs.log.{key}",
                        msg=f"Unknown log mode: {mode}",
                    )
                )
        if (log_cfg.get("stdout") == "file" or log_cfg.get("stderr") == "file") and not log_cfg.get("file_path"):
            issues.append(
                FlowValidationIssue(
                    code="semantic:external_process_log_file",
                    loc="inputs.log.file_path",
                    msg="log.file_path is required when stdout/stderr mode is 'file'",
                )
            )

    # idempotency sanity
    idem = step_inputs.get("idempotency") or {}
    if isinstance(idem, dict):
        strat = (idem.get("strategy") or "none")
        if strat == "atomic_dir":
            if not idem.get("temp_output_dir") or not idem.get("final_output_dir"):
                issues.append(
                    FlowValidationIssue(
                        code="semantic:external_process_atomic_dir",
                        loc="inputs.idempotency",
                        msg="atomic_dir requires temp_output_dir and final_output_dir",
                    )
                )
    return issues


def _fmt_loc(loc: Any) -> str:
    """Format a pydantic 'loc' tuple/list into a readable YAML-ish path."""
    if not loc:
        return "<root>"
    parts: List[str] = []
    for x in loc:
        if isinstance(x, int):
            # list index
            if not parts:
                parts.append(f"[{x}]")
            else:
                parts[-1] = f"{parts[-1]}[{x}]"
        else:
            parts.append(str(x))
    return ".".join(parts)


def _collect_pydantic_issues(err: ValidationError) -> List[FlowValidationIssue]:
    out: List[FlowValidationIssue] = []
    for e in err.errors():
        loc = _fmt_loc(e.get("loc"))
        msg = e.get("msg") or "Invalid value"
        etype = e.get("type") or "schema_error"
        out.append(FlowValidationIssue(code=f"schema:{etype}", loc=loc, msg=msg))
    return out


_ALLOWED_WHEN_AST_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.Name,
    ast.Attribute,
    ast.Constant,
    ast.Load,
)


def _validate_when_expr(expr: Optional[str]) -> Optional[str]:
    if expr is None:
        return None
    raw = (expr or "").strip()
    if not raw:
        return None

    # normalize booleans for parsing
    norm = raw.replace(" true", " True").replace(" false", " False")
    norm = norm.replace("==true", "== True").replace("==false", "== False")
    norm = norm.replace("!=true", "!= True").replace("!=false", "!= False")

    try:
        tree = ast.parse(norm, mode="eval")
    except SyntaxError as e:
        return f"Syntax error: {e.msg}"

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_WHEN_AST_NODES):
            return f"Unsupported node: {type(node).__name__}"
        if isinstance(node, ast.Name) and node.id not in {"jobs", "True", "False"}:
            return f"Unsupported name: {node.id}"
    return None


def _iter_strings(obj: Any, *, base_loc: str) -> List[tuple[str, str]]:
    """Return list of (loc, string) for all string values in a nested structure."""
    out: List[tuple[str, str]] = []

    def _walk(x: Any, loc: str) -> None:
        if isinstance(x, str):
            out.append((loc, x))
            return
        if isinstance(x, dict):
            for k, v in x.items():
                k2 = str(k)
                _walk(v, f"{loc}.{k2}" if loc else k2)
            return
        if isinstance(x, list):
            for i, v in enumerate(x):
                _walk(v, f"{loc}[{i}]")
            return

    _walk(obj, base_loc)
    return out


def _runtime_template_targets(flow_raw: dict) -> List[tuple[str, Any, str]]:
    """Collect only runtime-templated subtrees.

    Returns a list of (loc_prefix, obj, kind) where kind in {"resource", "step"}.
    """
    targets: List[tuple[str, Any, str]] = []

    resources = flow_raw.get("resources") or {}
    if isinstance(resources, dict):
        for rname, r in resources.items():
            if not isinstance(r, dict):
                continue
            if "config" in r:
                targets.append((f"resources.{rname}.config", r.get("config"), "resource"))
            if "options" in r:
                targets.append((f"resources.{rname}.options", r.get("options"), "resource"))
            if "decode" in r:
                targets.append((f"resources.{rname}.decode", r.get("decode"), "resource"))

    jobs = flow_raw.get("jobs") or []
    if isinstance(jobs, list):
        for ji, job in enumerate(jobs):
            if not isinstance(job, dict):
                continue
            steps = job.get("steps") or []
            if not isinstance(steps, list):
                continue
            for si, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                # only inputs/outputs are runtime-templated
                targets.append((f"jobs[{ji}].steps[{si}].inputs", step.get("inputs") or {}, "step"))
                targets.append((f"jobs[{ji}].steps[{si}].outputs", step.get("outputs") or {}, "step"))

    return targets


def validate_flow_dict(
    raw: dict,
    *,
    settings: Settings | None = None,
    flow_path: str | None = None,
    env_snapshot: dict[str, str] | None = None,
    archive_allowlist: set[str] | None = {},
) -> dict:
    """Validate flow config (schema + semantic checks).

    Returns a report dict: {ok: bool, errors: [{code, loc, msg}...]}
    """
    settings = settings or load_settings(env=env_snapshot)

    # Load plugins so validation can see third-party step types too.
    load_all_plugins(settings=settings)

    issues: List[FlowValidationIssue] = []
    warnings: List[FlowValidationIssue] = []

    try:
        spec = FlowSpec.model_validate(raw)
    except ValidationError as e:
        issues.extend(_collect_pydantic_issues(e))
        return {"ok": False, "errors": [x.as_dict() for x in issues], "flow_yaml": flow_path}
    except Exception as e:
        raise SpecError(str(e)) from e

    # ---- Semantic validation ----

    # Enterprise policy: lock down archive drivers. (internal_fast can be open)
    mode = str((env_snapshot or {}).get("AETHERFLOW_MODE", "internal_fast")).strip().lower()
    if mode == "enterprise":
        for rname, r in (spec.resources or {}).items():
            if r.kind == "archive" and r.driver not in archive_allowlist:
                issues.append(
                    FlowValidationIssue(
                        code="semantic:enterprise_archive_driver",
                        loc=f"resources.{rname}.driver",
                        msg=f"Enterprise mode requires archive driver in {sorted(archive_allowlist)}; got {r.driver!r}",
                    )
                )
    # Job IDs unique
    job_ids = [j.id for j in spec.jobs]
    dup_jobs = sorted({jid for jid in job_ids if job_ids.count(jid) > 1})
    for jid in dup_jobs:
        issues.append(FlowValidationIssue(code="semantic:duplicate_job_id", loc="jobs", msg=f"Duplicate job id: {jid}"))

    # Step IDs unique within each job
    for j_idx, job in enumerate(spec.jobs):
        step_ids = [s.id for s in job.steps]
        dup_steps = sorted({sid for sid in step_ids if step_ids.count(sid) > 1})
        for sid in dup_steps:
            issues.append(
                FlowValidationIssue(
                    code="semantic:duplicate_step_id",
                    loc=f"jobs[{j_idx}].steps",
                    msg=f"Duplicate step id in job '{job.id}': {sid}",
                )
            )

    # depends_on references exist and ordering
    job_idx = {jid: i for i, jid in enumerate(job_ids)}
    for j_i, job in enumerate(spec.jobs):
        for dep in job.depends_on:
            if dep not in job_idx:
                issues.append(
                    FlowValidationIssue(
                        code="semantic:depends_on_unknown_job",
                        loc=f"jobs[{j_i}].depends_on",
                        msg=f"Job '{job.id}' depends_on unknown job: {dep}",
                    )
                )
                continue
            if job_idx[dep] > job_idx.get(job.id, j_i):
                issues.append(
                    FlowValidationIssue(
                        code="semantic:depends_on_order",
                        loc=f"jobs[{j_i}].depends_on",
                        msg=f"Job '{job.id}' depends_on '{dep}' which appears after it; reorder jobs",
                    )
                )

    # Step types exist (including plugins)
    known_steps = set(list_steps())
    for j_i, job in enumerate(spec.jobs):
        for s_i, step in enumerate(job.steps):
            if step.type not in known_steps:
                issues.append(
                    FlowValidationIssue(
                        code="semantic:unknown_step_type",
                        loc=f"jobs[{j_i}].steps[{s_i}].type",
                        msg=f"Unknown step type: {step.type}. Loaded: {sorted(known_steps)}",
                    )
                )
            # Built-in: external.process extra semantic checks
            if step.type == "external.process":
                for iss in _validate_external_process(step.inputs):
                    issues.append(
                        FlowValidationIssue(
                            code=iss.code,
                            loc=f"jobs[{j_i}].steps[{s_i}].{iss.loc}",
                            msg=iss.msg,
                        )
                    )

    # when expression parse/safety check
    for j_i, job in enumerate(spec.jobs):
        err = _validate_when_expr(job.when)
        if err:
            issues.append(
                FlowValidationIssue(
                    code="semantic:invalid_when",
                    loc=f"jobs[{j_i}].when",
                    msg=err,
                )
            )

    return {
        "ok": len(issues) == 0,
        "errors": [x.as_dict() for x in issues],
        "warnings": [x.as_dict() for x in warnings],
        "flow_yaml": flow_path,
    }


def validate_flow_yaml(
    flow_yaml: str,
    *,
    settings: Settings | None = None,
    bundle_manifest: str | None = None,
    allow_stale_bundle: bool = False,
) -> dict:
    """Validate a flow YAML.

    This performs:
      1) schema + semantic validation of the flow YAML
      2) optional doctor env/profile checks (missing env keys referenced by profiles)

    Env/profile checks default to warnings (non-breaking). If you want them to fail validation,
    set AETHERFLOW_VALIDATE_ENV_STRICT=true.
    """
    env_snapshot, settings2, bundle_root, _env_sources, allowed_archive_drivers = build_env_snapshot(
        settings=settings,
        bundle_manifest=bundle_manifest,
        allow_stale_bundle=allow_stale_bundle,
    )
    settings = settings2

    path = Path(flow_yaml)
    # If validating via bundle, flow path may be relative to bundle root.
    if bundle_root and not path.is_absolute():
        path = (Path(bundle_root) / path)

    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    report = validate_flow_dict(raw, settings=settings, flow_path=str(path), env_snapshot=env_snapshot, archive_allowlist=allowed_archive_drivers)

    # Shared scan for runtime-templated fields (single source of truth)
    strict_env = (env_snapshot.get("AETHERFLOW_VALIDATE_ENV_STRICT", "false").lower() == "true")

    try:
        spec = FlowSpec.model_validate(raw)
    except ValidationError:
        # Schema errors already captured in report
        return report
    except Exception as e:
        raise SpecError(str(e)) from e

    scan = scan_runtime_templates(spec, env_snapshot=env_snapshot, strict_env=strict_env)
    report.setdefault("errors", []).extend([x.as_dict() for x in scan.errors])
    report.setdefault("warnings", []).extend([x.as_dict() for x in scan.warnings])

    # Profiles scan (also shared, to keep validation/diagnostics consistent)
    try:
        profiles_obj = None
        profiles_json = env_snapshot.get("AETHERFLOW_PROFILES_JSON")
        profiles_path = env_snapshot.get("AETHERFLOW_PROFILES_FILE")
        if profiles_json:
            import json as _json

            profiles_obj = _json.loads(profiles_json)
        elif profiles_path:
            pp = Path(profiles_path)
            if pp.exists():
                profiles_obj = yaml.safe_load(pp.read_text(encoding="utf-8")) or {}
        if profiles_obj is not None:
            pscan = scan_profiles_templates(profiles_obj, env_snapshot=env_snapshot, strict_env=strict_env)
            report["errors"].extend([x.as_dict() for x in pscan.errors])
            report["warnings"].extend([x.as_dict() for x in pscan.warnings])
    except Exception:
        log.warning(
            "failed to scan profiles for templates; continuing", exc_info=True
        )

    report["ok"] = len(report.get("errors") or []) == 0
    return report