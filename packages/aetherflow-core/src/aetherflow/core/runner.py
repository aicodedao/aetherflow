from __future__ import annotations

import logging
import importlib
import importlib.util
import os
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, override

import ast
from types import SimpleNamespace

import yaml

# Ensure built-in connectors/steps/resolvers are registered even when calling
# aetherflow.core.runner.run_flow directly.
from aetherflow.core.runtime import _bootstrap  # noqa: F401

from aetherflow.core.context import RunContext, new_run_id
from aetherflow.core.plugins import load_all_plugins
from aetherflow.core.connectors.manager import Connectors
from aetherflow.core.registry.steps import get_step
from aetherflow.core.runtime.settings import Settings, load_settings
from aetherflow.core.spec import BundleManifestSpec, ProfilesFileSpec, FlowSpec, FlowMetaSpec, RemoteFileMeta
from pydantic import ValidationError
from aetherflow.core.exception import SpecError, ResolverMissingKeyError, ResolverSyntaxError
from aetherflow.core.resolution import resolve_resource, resolve_flow_meta_templates, resolve_step_templates
from aetherflow.core.steps.base import StepResult, STEP_SUCCESS, STEP_SKIPPED
from aetherflow.core.state import StateStore
from aetherflow.core.observability import RunObserver
from aetherflow.core.bundles import sync_bundle
from aetherflow.core.runtime.envfiles import load_env_files, parse_env_files_json, parse_env_files_manifest
from aetherflow.core.validation import validate_flow_yaml

JOB_SUCCESS = "SUCCESS"
JOB_FAILED = "FAILED"
JOB_BLOCKED = "BLOCKED"
JOB_SKIPPED = "SKIPPED"

log = logging.getLogger("aetherflow.core.runner")


def _to_ns(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_ns(x) for x in obj]
    return obj


_ALLOWED_AST_NODES = (
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


def _safe_eval_when(expr: str, *, ctx: dict) -> bool:
    """Evaluate a small, safe subset of expressions for job gating.

    Supported:
      - jobs.<job_id>.outputs.<key>
      - ==, !=, >, >=, <, <=
      - and/or/not
      - true/false literals (case-insensitive)
    """
    if expr is None:
        return True
    raw = (expr or "").strip()
    if not raw:
        return True

    # normalize booleans
    norm = raw.replace(" true", " True").replace(" false", " False")
    norm = norm.replace("==true", "== True").replace("==false", "== False")
    norm = norm.replace("!=true", "!= True").replace("!=false", "!= False")

    tree = ast.parse(norm, mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(f"Unsupported expression in job.when: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in {"jobs", "True", "False"}:
            raise ValueError(f"Unsupported name in job.when: {node.id}")

    safe_globals = {"__builtins__": {}}
    safe_locals = {"jobs": _to_ns(ctx.get("jobs") or {})}
    return bool(eval(compile(tree, filename="<when>", mode="eval"), safe_globals, safe_locals))


def _ensure_logging(settings: Settings) -> None:
    # fmt = "%(asctime)s %(levelname)s %(name)s - %(message)s"
    fmt = '%(asctime)s - (%(threadName)-10s) - %(name)s - %(levelname)s - %(message)s'
    if (settings.log_format or "text").lower() == "json":
        # JSON payload already includes timestamp; keep formatter minimal.
        fmt = "%(message)s"
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=fmt,
    )


def _load_profiles(env: dict[str, str]) -> dict:
    profiles_json = env.get("AETHERFLOW_PROFILES_JSON")
    profiles_file = env.get("AETHERFLOW_PROFILES_FILE")
    if profiles_json and profiles_file:
        raise ValueError("Set only one of AETHERFLOW_PROFILES_JSON or AETHERFLOW_PROFILES_FILE")
    try:
        if profiles_json:
            import json
            raw = json.loads(profiles_json)
        elif profiles_file:
            with open(profiles_file, "r", encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
        else:
            return {}
        return ProfilesFileSpec.model_validate(raw).model_dump()
    except Exception as e:
        raise ValueError("Invalid profile configuration") from e


def _load_set_envs_module(settings: Settings):
    """Load set_envs/secrets hook module object.

    Uses Settings.secrets_module or Settings.secrets_path. If neither is set, returns None.
    """
    if settings.secrets_module:
        return importlib.import_module(settings.secrets_module)
    if settings.secrets_path:
        from pathlib import Path as _Path
        p = _Path(settings.secrets_path).expanduser().resolve()
        spec = importlib.util.spec_from_file_location(f"aetherflow_set_envs_{p.stem}", p)
        if not spec or not spec.loader:
            raise RuntimeError(f"Unable to load secrets module from path: {p}")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    return None


def _deep_merge_dict(base: dict, override: dict) -> dict:
    """Deep-merge two dictionaries.

    - Mapping values are merged recursively
    - Other values are overwritten by override
    - Sequences (list/tuple) are overwritten (not concatenated)

    We use this for config/options so profile defaults don't get blown away
    when a resource overrides just one nested key.
    """
    out: dict = {}
    base = base or {}
    override = override or {}
    for k, v in base.items():
        out[k] = v
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _merge_decode(profile_decode: dict | None, resource_decode: dict | None) -> dict:
    """Merge decode specs without losing nested paths.

    Supported decode shapes include nested bool maps (decode.config/ decode.options)
    and path lists (decode.config_paths / decode.options_paths). We merge:
      - nested bool maps via deep merge
      - *_paths lists via concatenation + de-dupe
      - other keys: override wins
    """
    pd = dict(profile_decode or {})
    rd = dict(resource_decode or {})
    out: dict = {}
    # start with profile
    for k, v in pd.items():
        out[k] = v

    for k, v in rd.items():
        if k in {"config", "options"} and isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
            continue
        if k in {"config_paths", "options_paths"}:
            existing = out.get(k)
            merged: list = []
            if isinstance(existing, list):
                merged.extend(existing)
            if isinstance(v, list):
                merged.extend(v)
            # de-dupe preserve order
            seen = set()
            deduped = []
            for item in merged:
                if item not in seen:
                    seen.add(item)
                    deduped.append(item)
            out[k] = deduped
            continue
        # generic mapping merge when both are dicts
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
            continue
        out[k] = v

    return out


def _build_resources(spec: FlowSpec, profiles: dict, env_snapshot: dict, settings: Settings, archive_allowlist: set) -> dict:
    env = dict(env_snapshot)

    set_envs_mod = _load_set_envs_module(settings)

    resources_final: Dict[str, dict] = {}
    mode = str(env.get("AETHERFLOW_MODE", "internal_fast")).strip().lower()
    for name, r in spec.resources.items():
        # Enterprise policy: keep archive drivers locked down.
        if mode == "enterprise" and r.kind == "archive" and (r.driver not in archive_allowlist):
            raise ValueError(
                f"Enterprise mode requires resources.{name}.driver to be one of {sorted(archive_allowlist)} for kind=archive. "
                f"Got: {r.driver!r}"
            )

        prof = profiles.get(r.profile, {}) if getattr(r, "profile", None) else {}

        config: Dict[str, Any] = _deep_merge_dict(prof.get("config", {}) or {}, r.config or {})
        options: Dict[str, Any] = _deep_merge_dict(prof.get("options", {}) or {}, r.options or {})
        decode: Dict[str, Any] = _merge_decode(prof.get("decode", {}) or {}, getattr(r, "decode", None) or {})

        resource_dict = {"kind": r.kind, "driver": r.driver, "config": config, "options": options, "decode": decode}
        resolved = resolve_resource(resource_dict, env=env, set_envs_module=set_envs_mod)

        resources_final[name] = {
            "kind": resolved.get("kind", r.kind),
            "driver": resolved.get("driver", r.driver),
            "config": resolved.get("config", {}),
            "options": resolved.get("options", {}),
            "decode": resolved.get("decode", decode),
        }

    return resources_final


def _build_connectors(resources: dict, ctx: RunContext) -> Connectors:
    # Lazy connector accessor with caching; avoids upfront instantiation
    # and allows per-call cache overrides.
    return Connectors(ctx=ctx, resources=resources, settings=ctx.settings)


def run_flow(
    flow_yaml: str,
    *,
    settings: Settings | None = None,
    run_id: str | None = None,
    flow_job: str | None = None,
    bundle_manifest: str | None = None,
    allow_stale_bundle: bool = False,
) -> None:
    # Guardrail: enforce the same strict validation pipeline for ALL entrypoints.
    # This prevents any new CLI/routes from bypassing template/semantic checks.
    report = validate_flow_yaml(
        flow_yaml,
        settings=settings,
        bundle_manifest=bundle_manifest,
        allow_stale_bundle=allow_stale_bundle,
    )
    if not report.get("ok", False):
        # Surface first error (if any) but keep the full report in logs.
        errs = report.get("errors") or []
        first = errs[0] if errs else {"msg": "Validation failed"}
        raise SpecError(first.get("msg") or "Validation failed")
    else:
        print(f"Validated bundle/flow yaml {report}")

    # Build a deterministic env snapshot for this run. We do NOT mutate os.environ.
    env_snapshot: Dict[str, str] = {k: str(v) for k, v in os.environ.items()}

    # Optional: load env files into snapshot (dotenv/json/dir). This is opt-in and
    # does not change behavior unless configured.
    env_files_json = env_snapshot.get("AETHERFLOW_ENV_FILES_JSON")
    if env_files_json:
        specs = parse_env_files_json(env_files_json)
        env_snapshot.update(load_env_files(specs))

    # Optional: sync a remote bundle (flows/profiles/plugins) into local disk before running.
    # This allows scheduler/run to use SFTP/SMB/DB/REST as the source of truth.
    archive_allowlist = {}
    br = None
    if bundle_manifest:
        base_settings = settings or load_settings(env=env_snapshot)
        br = sync_bundle(bundle_manifest=bundle_manifest, settings=base_settings, env_snapshot=env_snapshot, allow_stale=allow_stale_bundle)

        raw = yaml.safe_load(open(bundle_manifest, "r", encoding="utf-8")) or {}
        mf = BundleManifestSpec.model_validate(raw).model_dump()
        mode = str((mf.get("mode") or "internal_fast")).strip().lower()
        # Persist mode into env snapshot so downstream components (validation/resource builder)
        # can enforce mode-specific policies.
        env_snapshot["AETHERFLOW_MODE"] = mode
        env_snapshot["AETHERFLOW_MODE_ENTERPRISE"] = str((mode == "enterprise"))
        bundle = mf.get("bundle") or {}
        layout = bundle.get("layout") or {}

        # Enterprise policy: prefer trusted plugin paths configured in manifest.paths.plugins.
        # This avoids accidentally loading untrusted code via ambient env vars.
        if mode == "enterprise":
            # HARD DENY: never inherit plugin paths from the ambient OS environment.
            # Enterprise deployments are expected to load only preinstalled / trusted plugins.
            env_snapshot.pop("AETHERFLOW_STRICT_SANDBOX", True)
            env_snapshot.pop("AETHERFLOW_PLUGIN_PATHS", None)
            paths_cfg = mf.get("paths") or {}
            trusted_plugins = paths_cfg.get("plugins") or []
            if isinstance(trusted_plugins, str):
                trusted_plugins = [trusted_plugins]
            trusted_plugins = [str(p) for p in trusted_plugins if str(p).strip()]
            if trusted_plugins:
                env_snapshot["AETHERFLOW_PLUGIN_PATHS"] = ",".join(trusted_plugins)

        # Optional: env files specified in manifest. These are resolved relative to
        # the synced local bundle root (so remote bundles can carry env defaults).
        try:
            mf_specs = parse_env_files_manifest(mf)
            if mf_specs:
                env_snapshot.update(load_env_files(mf_specs, base_dir=br.local_root))
        except Exception as e:
            log.warning("failed loading env_files from manifest; continuing", exc_info=True)

        profiles_file = layout.get("profiles_file")
        plugins_dir = layout.get("plugins_dir")
        if profiles_file:
            env_snapshot["AETHERFLOW_PROFILES_FILE"] = str((br.local_root / profiles_file).resolve())
        # IMPORTANT: enterprise mode must not map bundle plugins into AETHERFLOW_PLUGIN_PATHS.
        # Plugins are expected to be preinstalled/trusted in enterprise deployments.
        if plugins_dir and mode != "enterprise":
            env_snapshot["AETHERFLOW_PLUGIN_PATHS"] = str((br.local_root / plugins_dir).resolve())

        entry = str(bundle.get("entry_flow") or "").strip()
        if entry:
            flow_yaml = str((br.local_root / entry).resolve())
        else:
            if not os.path.isabs(flow_yaml):
                flow_yaml = str((br.local_root / flow_yaml).resolve())

        archive_allowlist = mf.get("zip_drivers")

    # Load Flow yaml
    with open(flow_yaml, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    try:
        spec = FlowSpec.model_validate(raw)
    except ValidationError as e:
        raise SpecError(str(e)) from e

    # FlowMeta: resolver
    parsed_flow_meta = FlowMetaSpec.model_validate(resolve_flow_meta_templates(spec.flow.model_dump(), env_snapshot=dict(env_snapshot)))

    run_id = run_id or new_run_id()
    flow_id = parsed_flow_meta.id

    # Settings should be derived from the same env snapshot for predictability.
    settings = settings or load_settings(env=env_snapshot, overrides={"work_root": Path(parsed_flow_meta.workspace.root)})
    _ensure_logging(settings)
    
    # Setup standard directories
    work_root = Path(parsed_flow_meta.workspace.root) or settings.work_root
    env_snapshot["AETHERFLOW_LOCAL_ROOT_DIR"] = str(br.local_root) if br else work_root
    env_snapshot["AETHERFLOW_ACTIVE_DIR"] = str(br.active_dir) if br else work_root
    env_snapshot["AETHERFLOW_CACHE_DIR"] = str(br.cache_dir) if br else work_root

    # Load Plugins (Connectors, Steps)
    load_all_plugins(settings=settings)

    ctx = RunContext(
        settings=settings,
        flow_id=flow_id,
        run_id=run_id,
        work_root=work_root,
        layout=parsed_flow_meta.workspace.layout,
        state=StateStore(parsed_flow_meta.state.path),
        resources={},
        env=env_snapshot,
    )
    ctx.log = logging.getLogger(f"aetherflow.flow.{flow_id}")

    obs = RunObserver(settings=settings, logger=ctx.log, flow_id=flow_id, run_id=run_id)
    obs.run_start(yaml_path=flow_yaml)

    profiles = _load_profiles(ctx.env)

    # env snapshot: stable for this run (already computed and stored in ctx.env)
    ctx.resources = _build_resources(spec, profiles=profiles, env_snapshot=ctx.env, settings=settings, archive_allowlist=archive_allowlist)
    ctx.connectors = _build_connectors(resources=ctx.resources, ctx=ctx)

    job_ids = [j.id for j in spec.jobs]
    job_idx = {jid: i for i, jid in enumerate(job_ids)}
    for j in spec.jobs:
        for dep in j.depends_on:
            if dep not in job_idx:
                raise ValueError(f"Job {j.id} depends_on unknown job: {dep}")
            if job_idx[dep] > job_idx[j.id]:
                raise ValueError(f"Job {j.id} depends_on {dep} which appears after it; reorder jobs")

    statuses: Dict[str, str] = {}
    job_ctx: Dict[str, Any] = {}  # job_id -> {status, outputs}
    base_tpl: Dict[str, Any] = {
        "run_id": run_id,
        "flow_id": flow_id,
        "env": env_snapshot,
        "resources": ctx.resources,
        "jobs": job_ctx,
    }

    try:
        for job in spec.jobs:
            if flow_job and job.id != flow_job:
                continue

            if job.depends_on:
                ok = all(statuses.get(dep) == JOB_SUCCESS for dep in job.depends_on)
                if not ok:
                    ctx.log.warning(f"Job blocked job_id={job.id} depends_on={job.depends_on}")
                    statuses[job.id] = JOB_BLOCKED
                    job_ctx[job.id] = {"status": JOB_BLOCKED, "outputs": {}}
                    ctx.state.set_job_status(job.id, run_id, JOB_BLOCKED)
                    continue

            # Optional gating at job level.
            if job.when:
                try:
                    cond = _safe_eval_when(job.when, ctx=base_tpl)
                except Exception as e:
                    raise ValueError(f"Invalid job.when for job_id={job.id}: {e}")
                if not cond:
                    ctx.log.info(f"Job skipped job_id={job.id} when=({job.when})")
                    statuses[job.id] = JOB_SKIPPED
                    job_ctx[job.id] = {"status": JOB_SKIPPED, "outputs": {}, "skip_reason": "condition=false"}
                    ctx.state.set_job_status(job.id, run_id, JOB_SKIPPED)
                    continue

            ctx.state.set_job_status(job.id, run_id, "RUNNING")
            job_log = logging.getLogger(f"aetherflow.flow.{flow_id}.job.{job.id}")
            obs.job_start(job_id=job.id)

            job_dir = ctx.job_dir(job.id)
            ctx.artifacts_dir(job.id)
            ctx.scratch_dir(job.id)
            ctx.manifests_dir(job.id)

            step_outputs: Dict[str, Dict[str, Any]] = {}
            job_outputs: Dict[str, Any] = {}
            job_tpl = dict(base_tpl)
            job_tpl["job_id"] = job.id
            job_tpl["steps"] = step_outputs
            job_tpl["job_outputs"] = job_outputs

            try:
                skip_rest = False
                skip_reason: Optional[str] = None

                for step in job.steps:
                    if skip_rest:
                        job_log.info(f"Step skipped (job short-circuit) step_id={step.id} reason={skip_reason}")
                        ctx.state.set_step_status(job.id, run_id, step.id, STEP_SKIPPED)
                        step_outputs[step.id] = {"skipped": True, "reason": skip_reason}
                        continue

                    prev = ctx.state.get_step_status(job.id, run_id, step.id)
                    if prev in (STEP_SUCCESS, STEP_SKIPPED):
                        job_log.info(f"Step skip (resume) step_id={step.id} prev={prev}")
                        continue

                    StepCls = get_step(step.type)
                    runtime_ctx_in = {
                        "env": ctx.env,
                        "steps": step_outputs,
                        "job": {"id": job.id, "outputs": job_outputs},
                        "run_id": run_id,
                        "flow_id": flow_id,
                        "result": {},
                        "jobs": job_ctx
                    }
                    rendered_inputs = resolve_step_templates(step.inputs, runtime_ctx_in)

                    obs.step_start(job_id=job.id, step_id=step.id, step_type=step.type)

                    inst = StepCls(step.id, rendered_inputs, ctx, job.id)
                    raw_out = inst.run()

                    if isinstance(raw_out, StepResult):
                        step_status = raw_out.status
                        out = raw_out.as_output()
                    else:
                        step_status = STEP_SUCCESS
                        out = raw_out or {}

                    step_outputs[step.id] = out
                    ctx.state.set_step_status(job.id, run_id, step.id, step_status)

                    # Promote declared step outputs to job outputs (for downstream job gating).
                    if step.outputs:
                        runtime_ctx_out = {
                            "env": ctx.env,
                            "steps": step_outputs,
                            "job": {"id": job.id, "outputs": job_outputs},
                            "run_id": run_id,
                            "flow_id": flow_id,
                            "result": out,
                            "jobs": job_ctx
                        }
                        rendered = resolve_step_templates(step.outputs, runtime_ctx_out)
                        job_outputs.update(rendered or {})

                    if step_status == STEP_SKIPPED:
                        obs.step_end(job_id=job.id, step_id=step.id, step_type=step.type, status=STEP_SKIPPED)
                        # Short-circuit the rest of the job if explicitly requested.
                        if step.on_no_data == "skip_job":
                            skip_rest = True
                            skip_reason = out.get("reason") or "step requested skip_job"
                            job_log.info(f"Job short-circuit after step_id={step.id} reason={skip_reason}")
                    else:
                        obs.step_end(job_id=job.id, step_id=step.id, step_type=step.type, status=STEP_SUCCESS)

                # Job status: if we short-circuited due to no data, mark job as SKIPPED.
                if skip_rest and all(ctx.state.get_step_status(job.id, run_id, s.id) in (STEP_SUCCESS, STEP_SKIPPED) for s in job.steps):
                    ctx.state.set_job_status(job.id, run_id, JOB_SKIPPED)
                    statuses[job.id] = JOB_SKIPPED
                    job_ctx[job.id] = {"status": JOB_SKIPPED, "outputs": job_outputs, "skip_reason": skip_reason, "skip_trigger": "step"}
                    job_log.info(f"Job skipped (no data) reason={skip_reason}")
                    obs.job_end(job_id=job.id, status=JOB_SKIPPED, skip_reason=skip_reason)
                else:
                    ctx.state.set_job_status(job.id, run_id, JOB_SUCCESS)
                    statuses[job.id] = JOB_SUCCESS
                    job_ctx[job.id] = {"status": JOB_SUCCESS, "outputs": job_outputs}
                    job_log.info("Job success")
                    obs.job_end(job_id=job.id, status=JOB_SUCCESS)

                pol = parsed_flow_meta.workspace.cleanup_policy
                if pol in ("on_success", "always"):
                    shutil.rmtree(job_dir, ignore_errors=True)
                    job_log.info("Job cleaned up")
            except Exception as e:
                ctx.state.set_job_status(job.id, run_id, JOB_FAILED)
                statuses[job.id] = JOB_FAILED
                job_log.exception(f"Job failed: {e}")
                obs.job_end(job_id=job.id, status=JOB_FAILED)

                if parsed_flow_meta.workspace.cleanup_policy == "always":
                    shutil.rmtree(job_dir, ignore_errors=True)
                raise

        # Summarize at end (also emitted in structured form when log_format=json).
        counts: Dict[str, int] = {}
        for st in statuses.values():
            counts[st] = counts.get(st, 0) + 1
        obs.run_end(status_counts=counts)
    finally:
        # Best-effort close run-scoped connectors.
        try:
            if hasattr(ctx.connectors, "close_all"):
                ctx.connectors.close_all()  # type: ignore[attr-defined]
        except Exception:
            pass