from __future__ import annotations

import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from aetherflow.core.diagnostics.env_snapshot import build_env_snapshot
from aetherflow.core.spec import FlowSpec
from pydantic import ValidationError
from aetherflow.core.exception import SpecError

log = logging.getLogger('aetherflow.core.diagnostics')


def _load_profiles_from_env(env: Dict[str, str]) -> Dict[str, Any]:
    profiles_json = env.get("AETHERFLOW_PROFILES_JSON")
    profiles_file = env.get("AETHERFLOW_PROFILES_FILE")
    if profiles_json:
        return json.loads(profiles_json)
    if profiles_file:
        p = Path(profiles_file)
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {}


def _decode_sets(profile: Dict[str, Any]) -> Tuple[set[str], set[str]]:
    dec = profile.get("decode") or {}
    cfg = dec.get("config") or []
    opt = dec.get("options") or []
    if isinstance(cfg, dict):
        cfg = [k for k, v in cfg.items() if bool(v)]
    if isinstance(opt, dict):
        opt = [k for k, v in opt.items() if bool(v)]
    return set(cfg), set(opt)


def _required_env_keys_for_resource(
    *,
    profile: Dict[str, Any],
    resource_config: Dict[str, Any],
    resource_options: Dict[str, Any],
) -> List[Tuple[str, str, str]]:
    """Profiles no longer support config/options mapping."""
    _ = (profile, resource_config, resource_options)
    return []


def doctor_check_env(
    flow_yaml: str,
    *,
    bundle_manifest: str | None = None,
    allow_stale_bundle: bool = False,
) -> Dict[str, Any]:
    """Doctor check for missing env keys referenced by templates.

    With the single-resolver architecture, the only supported env interpolation is
    via {{env.VAR}} or {{env.VAR:DEFAULT}} tokens. This check scans the flow YAML
    (and optional profiles data from env) and reports missing env keys where no
    DEFAULT is provided (or where the rendered env value is empty string).
    """
    env_snapshot, _settings, bundle_root, _env_sources, allowed_archive_drivers = build_env_snapshot(
        bundle_manifest=bundle_manifest,
        allow_stale_bundle=allow_stale_bundle,
    )

    # If running via bundle, flow may be relative to bundle root.
    if bundle_root and not os.path.isabs(flow_yaml):
        flow_yaml = str((Path(bundle_root) / flow_yaml).resolve())

    raw = yaml.safe_load(open(flow_yaml, "r", encoding="utf-8")) or {}
    try:
        spec = FlowSpec.model_validate(raw)
    except ValidationError as e:
        raise SpecError(str(e)) from e

    # Shared scanner from validation.py (single source of truth)
    from aetherflow.core.validation import scan_runtime_templates, scan_profiles_templates

    scan = scan_runtime_templates(spec, env_snapshot=env_snapshot, strict_env=False)
    missing: list[dict] = [x.as_dict() for x in scan.warnings if x.code == "semantic:missing_env"]
    reporting_warnings: list[dict] = [x.as_dict() for x in scan.errors if x.code.startswith("template:")]

    # Scan profiles data if provided via env (also shared)
    try:
        profiles_obj = _load_profiles_from_env(env_snapshot)
        if profiles_obj:
            pscan = scan_profiles_templates(profiles_obj, env_snapshot=env_snapshot, strict_env=False)
            missing.extend([x.as_dict() for x in pscan.warnings if x.code == "semantic:missing_env"])
            reporting_warnings.extend([x.as_dict() for x in pscan.errors if x.code.startswith("template:")])
    except Exception:
        log.warning(
            "failed to scan profiles for templates; continuing", exc_info=True
        )

    # Keep existing report-region warnings (non-fatal)
    try:
        jobs = raw.get("jobs") or []
        for ji, job in enumerate(jobs):
            steps = job.get("steps") or []
            for si, st in enumerate(steps):
                if (st.get("type") or "").strip() != "excel_fill_from_file":
                    continue
                inputs = st.get("inputs") or {}
                default_thr = inputs.get("rows_threshold")
                targets = inputs.get("targets") or []
                for ti, t in enumerate(targets):
                    mode = (t.get("mode") or "data_sheet").lower()
                    if mode != "report_region":
                        continue
                    t_thr = t.get("rows_threshold", default_thr)
                    fail_on = t.get("fail_on_threshold")
                    if t_thr is None:
                        reporting_warnings.append(
                            {
                                "loc": f"jobs[{ji}].steps[{si}].inputs.targets[{ti}]",
                                "code": "report_region_default_threshold",
                                "msg": "mode=report_region uses the default rows_threshold (50000). Consider setting rows_threshold explicitly or use mode=data_sheet (DATA_*).",
                            }
                        )
                    if fail_on is False or str(fail_on).lower() == "false":
                        reporting_warnings.append(
                            {
                                "loc": f"jobs[{ji}].steps[{si}].inputs.targets[{ti}]",
                                "code": "report_region_threshold_guard_disabled",
                                "msg": "mode=report_region has fail_on_threshold=false. This can create huge, slow workbooks. Prefer mode=data_sheet (DATA_*).",
                            }
                        )
    except Exception:
        import logging

        log.warning(
            "failed to compute report-region diagnostics warnings; continuing",
            exc_info=True,
        )

    ok = len(missing) == 0
    return {
        "ok": ok,
        "flow_yaml": flow_yaml,
        "missing_env": missing,
        "warnings": reporting_warnings,
    }


def _should_redact(*, env_key: str, field: str, decoded: bool) -> bool:
    if decoded:
        return True
    key = (env_key or "").upper()
    fld = (field or "").upper()
    sensitive = ("PASS" in key) or ("TOKEN" in key) or ("SECRET" in key) or ("KEY" in key)
    sensitive = sensitive or ("PASS" in fld) or ("TOKEN" in fld) or ("SECRET" in fld) or ("KEY" in fld)
    return bool(sensitive)


def explain_profiles_env(
    flow_yaml: str,
    *,
    bundle_manifest: str | None = None,
    allow_stale_bundle: bool = False,
) -> Dict[str, Any]:
    """Explain profile usage for each resource.

    Note: profiles no longer support config/options mapping; this report
    focuses on profile selection and decode configuration.
    """
    env_snapshot, settings, bundle_root, _env_sources, allowed_archive_drivers = build_env_snapshot(
        bundle_manifest=bundle_manifest, allow_stale_bundle=allow_stale_bundle
    )
    if bundle_root and not os.path.isabs(flow_yaml):
        flow_yaml = str((Path(bundle_root) / flow_yaml).resolve())

    raw = yaml.safe_load(open(flow_yaml, "r", encoding="utf-8")) or {}
    try:
        spec = FlowSpec.model_validate(raw)
    except ValidationError as e:
        raise SpecError(str(e)) from e
    profiles = _load_profiles_from_env(env_snapshot)

    resources_out: Dict[str, Any] = {}
    for rname, r in spec.resources.items():
        prof_name = r.profile
        if not prof_name:
            continue
        prof = profiles.get(prof_name) or {}
        resources_out[rname] = {
            "kind": r.kind,
            "driver": r.driver,
            "profile": prof_name,
            "decode": prof.get("decode") or {},
        }

    return {"flow_yaml": flow_yaml, "resources": resources_out}