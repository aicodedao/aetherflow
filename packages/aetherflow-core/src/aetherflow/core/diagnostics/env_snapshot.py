"""Environment snapshot builder (diagnostic-only).

This module is diagnostic-only; currently used by validation and diagnostics helpers.
Not used by runner/bundles at runtime.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

from aetherflow.core.runtime.envfiles import load_env_files, parse_env_files_json, parse_env_files_manifest
from aetherflow.core.runtime.secrets import load_secrets_provider
from aetherflow.core.runtime.settings import Settings, load_settings
from aetherflow.core.spec import BundleManifestSpec

log = logging.getLogger("aetherflow.core.diagnostics.env_snapshot.py")


def build_env_snapshot(
    *,
    settings: Optional[Settings] = None,
    bundle_manifest: str | None = None,
    allow_stale_bundle: bool = False,
) -> Tuple[Dict[str, str], Settings, str | None, Dict[str, str]]:
    """Build the deterministic env snapshot and optionally sync a bundle.

    Returns: (env_snapshot, settings, bundle_local_root, env_sources, archive_allowlist)

    env_sources maps env_key -> one of:
      - os
      - env_files
      - env_files_manifest
      - expanded
    """

    base_os: Dict[str, str] = {k: str(v) for k, v in os.environ.items()}
    env_snapshot: Dict[str, str] = dict(base_os)
    env_sources: Dict[str, str] = {k: "os" for k in env_snapshot.keys()}

    # opt-in: env_files via env var
    env_files_json = env_snapshot.get("AETHERFLOW_ENV_FILES_JSON")
    if env_files_json:
        loaded = load_env_files(parse_env_files_json(env_files_json))
        env_snapshot.update(loaded)
        for k in loaded.keys():
            env_sources[str(k)] = "env_files"

    archive_allowlist = {}
    bundle_root: str | None = None
    if bundle_manifest:
        # We reuse sync_bundle but only if it exists; import lazily to avoid cycles.
        from aetherflow.core.bundles import sync_bundle

        base_settings = settings or load_settings(env=env_snapshot)
        br = sync_bundle(
            bundle_manifest=bundle_manifest,
            settings=base_settings,
            env_snapshot=env_snapshot,
            allow_stale=allow_stale_bundle,
        )
        bundle_root = str(br.local_root)

        raw = yaml.safe_load(open(bundle_manifest, "r", encoding="utf-8")) or {}
        mf = BundleManifestSpec.model_validate(raw).model_dump()
        mode = str((mf.get("mode") or "internal_fast")).strip().lower()

        # Enterprise mode policy: prefer trusted plugin paths declared in manifest.paths.plugins
        # over any inherited OS/plugin paths.
        if mode == "enterprise":
            env_snapshot.pop("AETHERFLOW_PLUGIN_PATHS", None)
            paths_cfg = mf.get("paths") or {}
            trusted_plugins = paths_cfg.get("plugins") or []
            if isinstance(trusted_plugins, str):
                trusted_plugins = [trusted_plugins]
            trusted_plugins = [str(p) for p in trusted_plugins if str(p).strip()]
            if trusted_plugins:
                env_snapshot["AETHERFLOW_PLUGIN_PATHS"] = ",".join(trusted_plugins)

        # manifest env.files (optional)
        try:
            specs = parse_env_files_manifest(mf)
            if specs:
                loaded = load_env_files(specs, base_dir=Path(bundle_root))
                env_snapshot.update(loaded)
                for k in loaded.keys():
                    env_sources[str(k)] = "env_files_manifest"
        except Exception:
            log.warning(
                "failed to load env.files from manifest; continuing", exc_info=True
            )

        # set profiles/plugins paths for downstream tooling
        bundle = mf.get("bundle") or {}
        layout = (bundle.get("layout") or {})
        profiles_file = layout.get("profiles_file")
        plugins_dir = layout.get("plugins_dir")
        if profiles_file:
            env_snapshot["AETHERFLOW_PROFILES_FILE"] = str(
                (Path(bundle_root) / profiles_file).resolve()
            )
        if plugins_dir and mode != "enterprise":
            env_snapshot["AETHERFLOW_PLUGIN_PATHS"] = str(
                (Path(bundle_root) / plugins_dir).resolve()
            )

        archive_allowlist = mf.get("zip_drivers")

    settings = settings or load_settings(env=env_snapshot)

    # optional: expand env via secrets hook (set_envs.expand_env)
    provider = load_secrets_provider(
        secrets_module=settings.secrets_module, secrets_path=settings.secrets_path
    )
    if provider and getattr(provider, "expand_env", None):
        before = dict(env_snapshot)
        env_snapshot = provider.expand_env(dict(env_snapshot))
        for k, v in env_snapshot.items():
            if before.get(k) != v:
                env_sources[str(k)] = "expanded"

    return env_snapshot, settings, bundle_root, env_sources, archive_allowlist