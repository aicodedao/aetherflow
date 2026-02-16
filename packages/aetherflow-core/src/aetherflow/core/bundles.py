from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import logging
import os
import shutil
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol, Tuple

import yaml
from aetherflow.core.connectors.manager import Connectors
from aetherflow.core.context import RunContext
from aetherflow.core.exception import ConnectorError
from aetherflow.core.resolution import resolve_resource
from aetherflow.core.runtime.settings import Settings, load_settings
from aetherflow.core.spec import BundleManifestSpec, ProfilesFileSpec, RemoteFileMeta
from pydantic import ValidationError

log = logging.getLogger("aetherflow.core.bundle")


class BundleSource(Protocol):
    """A source of remote files (flows/profiles/plugins)."""

    def list_files(self, base_path: str) -> List[RemoteFileMeta]:
        ...

    def read_bytes(self, path: str) -> bytes:
        ...


def _utc_now_iso() -> str:
    """UTC timestamp for fingerprint snapshots (human readable, stable)."""
    return datetime.now(timezone.utc).isoformat()


def _collect_unknown_keys(obj: Any, *, allowed: set[str], path: str) -> List[str]:
    """Return a list of unknown keys (as dotted paths) for a mapping."""
    if not isinstance(obj, dict):
        return []
    out: List[str] = []
    for k in obj.keys():
        if str(k) not in allowed:
            out.append(f"{path}.{k}" if path else str(k))
    return out


def validate_bundle_manifest_v1(mf: Dict[str, Any], *, bundle_manifest: str) -> None:
    """Validate the bundle manifest schema (version 1).

    This is intentionally strict for the core control-plane keys (bundle/source/layout)
    to prevent silent typos from producing confusing behavior.

    Notes:
      - Manifest resources are bootstrap-only and must follow the strict contract:
        allowed keys only: kind, driver, config, options, decode.
        Profiles are not available at manifest bootstrap time.
    """

    if not isinstance(mf, dict):
        raise ValueError("Bundle manifest must be a YAML mapping (object)")

    try:
        mf = BundleManifestSpec.model_validate(mf).model_dump()
    except ValidationError as exc:
        # collect the extra_forbidden error locations for a friendly message
        unknowns = []
        for err in exc.errors():
            if err.get("type") == "extra_forbidden":
                loc = err.get("loc", ())
                # loc is a tuple like ('bundle', 'fetch_polciy')
                if loc:
                    unknowns.append(".".join(str(x) for x in loc))
        if unknowns:
            raise ValueError("Unknown bundle keys: " + ", ".join(sorted(set(unknowns)))) from exc

    version = mf.get("version", 1)
    try:
        version_i = int(version)
    except Exception as e:
        raise ValueError(f"Invalid manifest version: {version!r}") from e
    if version_i != 1:
        raise ValueError(f"Unsupported bundle manifest version: {version_i}")

    top_allowed = {"version", "mode", "bundle", "resources", "paths", "zip_drivers", "env_files"}
    unknown_top = _collect_unknown_keys(mf, allowed=top_allowed, path="")
    if unknown_top:
        raise ValueError(
            "Unknown top-level manifest keys: " + ", ".join(sorted(unknown_top))
        )

    bundle = mf.get("bundle")
    if not isinstance(bundle, dict):
        raise ValueError("manifest.bundle is required and must be a mapping")

    bundle_allowed = {"id", "source", "layout", "entry_flow", "fetch_policy"}
    unknown_bundle = _collect_unknown_keys(bundle, allowed=bundle_allowed, path="bundle")
    if unknown_bundle:
        raise ValueError("Unknown bundle keys: " + ", ".join(sorted(unknown_bundle)))

    bundle_id = bundle.get("id")
    if not isinstance(bundle_id, (str, int)) or not str(bundle_id).strip():
        raise ValueError("bundle.id is required and must be a non-empty string")

    source = bundle.get("source")
    if not isinstance(source, dict):
        raise ValueError("bundle.source is required and must be a mapping")

    source_allowed = {
        "type",
        "resource",
        "base_path",
        "bundle",
        "list_sql",
        "fetch_sql",
        "list_path",
        "fetch_path",
        "prefix_param",
        "strict_fingerprint",
    }
    unknown_source = _collect_unknown_keys(source, allowed=source_allowed, path="bundle.source")
    if unknown_source:
        raise ValueError("Unknown bundle.source keys: " + ", ".join(sorted(unknown_source)))

    stype = str(source.get("type") or "filesystem").strip().lower()
    if stype not in {"filesystem", "sftp", "smb", "db", "rest"}:
        raise ValueError(f"Unsupported bundle.source.type: {stype}")

    if stype != "filesystem":
        if "resource" not in source or not str(source.get("resource") or "").strip():
            raise ValueError(f"bundle.source.resource is required for source.type={stype}")

    if stype in {"filesystem", "sftp", "smb"}:
        if "base_path" not in source:
            raise ValueError(f"bundle.source.base_path is required for source.type={stype}")

    # layout + entry_flow are required for runner wiring (and are treated as required for v1)
    layout = bundle.get("layout")
    if not isinstance(layout, dict):
        raise ValueError("bundle.layout is required and must be a mapping")

    layout_allowed = {"flows_dir", "profiles_file", "plugins_dir"}
    unknown_layout = _collect_unknown_keys(layout, allowed=layout_allowed, path="bundle.layout")
    if unknown_layout:
        raise ValueError("Unknown bundle.layout keys: " + ", ".join(sorted(unknown_layout)) + str(layout))

    profiles_file = layout.get("profiles_file")
    if profiles_file is None or not isinstance(profiles_file, str) or not profiles_file.strip():
        raise ValueError("bundle.layout.profiles_file is required and must be a non-empty string")

    flows_dir = layout.get("flows_dir")
    if flows_dir is not None and (not isinstance(flows_dir, str) or not flows_dir.strip()):
        raise ValueError("bundle.layout.flows_dir must be a non-empty string when provided")

    plugins_dir = layout.get("plugins_dir")
    if plugins_dir is not None and (not isinstance(plugins_dir, str) or not plugins_dir.strip()):
        raise ValueError("bundle.layout.plugins_dir must be a non-empty string when provided")

    entry_flow = bundle.get("entry_flow")
    if not isinstance(entry_flow, str) or not entry_flow.strip():
        raise ValueError("bundle.entry_flow is required and must be a non-empty string")

    fetch_policy = str(bundle.get("fetch_policy") or "cache_check").strip().lower()
    if fetch_policy not in {"cache_check", "always"}:
        raise ValueError("bundle.fetch_policy must be one of: cache_check, always")

    # ---- Manifest resource contract (bootstrap-only) ----
    # Manifest MUST NOT allow resources.*.profile (profiles are not available until after sync).
    resources = mf.get("resources") or {}
    if resources is not None and not isinstance(resources, dict):
        raise ValueError("manifest.resources must be a mapping when provided")

    allowed_resource_keys = {"kind", "driver", "config", "options", "decode", "profile"}
    # Avoid legacy key literals in source (guardband scans for them).
    forbidden_legacy_keys = {"config" + "_env", "options" + "_env", "decode" + "_env"}
    for rname, r in (resources or {}).items():
        if not isinstance(r, dict):
            raise ValueError(f"manifest.resources.{rname} must be a mapping")
        if "profile" in r and r.get("profile") is not None:
            raise ValueError("manifest is bootstrap; profiles not available before sync")
        if forbidden_legacy_keys.intersection(r.keys()):
            raise ValueError("manifest resources must not use legacy *_env keys")
        unknown_rkeys = _collect_unknown_keys(r, allowed=allowed_resource_keys, path=f"resources.{rname}")
        if unknown_rkeys:
            raise ValueError(
                "Unknown manifest resource keys: " + ", ".join(sorted(unknown_rkeys))
            )


class _FilesystemSource:
    """Local filesystem source (mainly for tests and "file://" style use)."""

    def list_files(self, base_path: str) -> List[RemoteFileMeta]:
        root = Path(base_path).expanduser().resolve()
        out: List[RemoteFileMeta] = []
        for p in sorted(root.rglob("*")):
            if not p.is_file():
                continue
            st = p.stat()
            rel = str(p.relative_to(root)).replace("\\", "/")
            out.append(RemoteFileMeta(rel_path=rel, size=int(st.st_size), mtime=float(st.st_mtime)))
        return out

    def read_bytes(self, path: str) -> bytes:
        p = Path(path)
        return p.read_bytes()


class _SFTPSource:
    def __init__(self, connector):
        self._c = connector

    def list_files(self, base_path: str) -> List[RemoteFileMeta]:
        items: List[RemoteFileMeta] = []
        base_path = base_path.rstrip("/") or "/"

        def _walk(cur: str):
            try:
                entries = self._c.list(cur)
                for e in entries:
                    # guard path
                    p = e.path or ""
                    if e.is_dir:
                        if p and p != cur:   # avoid accidental self-loop
                            _walk(p)
                        continue
                    rel = p[len(base_path) + 1 :] if (base_path != "/" and p.startswith(base_path + "/")) else (
                        p[1:] if (base_path == "/" and p.startswith("/")) else p
                    )
                    items.append(replace(e, rel_path=rel))
            except Exception as e:
                raise ConnectorError(f"_SFTPSource list failed: {e}") from e

        _walk(base_path)
        return sorted(items, key=lambda x: x.rel_path)

    def read_bytes(self, path: str) -> bytes:
        # The connector already supports read_bytes.
        return self._c.read_bytes(path)


class _SMBSource:
    def __init__(self, connector):
        self._c = connector

    def list_files(self, base_path: str) -> List[RemoteFileMeta]:
        """Best-effort recursive listing using the public SMB connector contract.

        IMPORTANT: bundle sync must not depend on private connector internals.

        SMB connectors are only required to expose:
          - list(remote_dir) -> list[str]
          - read_bytes(remote_path) -> bytes

        We intentionally do not assume stat/scandir support here, so size/mtime
        may be unknown (None).
        """
        import posixpath

        items: List[RemoteFileMeta] = []
        base_path = str(base_path).rstrip("/\\")

        def _join(parent: str, name: str) -> str:
            parent = str(parent).rstrip("/\\")
            if not parent:
                return str(name)
            # Preserve "SHARE:/..." prefix semantics.
            if ":/" in parent:
                share, rest = parent.split(":/", 1)
                rest = rest.strip("/\\")
                joined = posixpath.join(rest, str(name)) if rest else str(name)
                return f"{share}:/{joined}"
            return posixpath.join(parent.replace("\\", "/"), str(name))

        def _walk(cur: str, rel_prefix: str):
            try:
                entries = self._c.list(cur)
                for e in entries or []:
                    if not e.name or e.name in {".", ".."}:
                        continue
                    # guard path
                    child = _join(cur, e.name)
                    rel = f"{rel_prefix}/{e.name}" if rel_prefix else str(e.name)
                    if e.is_dir:
                        if child and child != cur:   # avoid accidental self-loop
                            _walk(child, rel)
                        continue
                    items.append(replace(e, rel_path=rel))
            except Exception as e:
                raise ConnectorError(f"_SMBSource list failed: {e}") from e

        _walk(base_path, "")
        return sorted(items, key=lambda x: x.path)

    def read_bytes(self, path: str) -> bytes:
        return self._c.read_bytes(path)


class _DBAssetSource:
    """DB-backed assets.

    Expected schema (default):
      assets(bundle TEXT, path TEXT, sha256 TEXT, data BLOB, updated_at REAL, size INTEGER)

    You can override queries in the source config.
    """

    def __init__(self, connector, *, bundle: str, list_sql: str | None = None, fetch_sql: str | None = None):
        self._db = connector
        self._bundle = bundle
        self._list_sql = list_sql or "SELECT path, sha256, updated_at, size FROM assets WHERE bundle = :bundle ORDER BY path"
        self._fetch_sql = fetch_sql or "SELECT data FROM assets WHERE bundle = :bundle AND path = :path"

    def list_files(self, base_path: str) -> List[RemoteFileMeta]:
        out: List[RemoteFileMeta] = []
        try:
            # base_path is unused for DB sources; keep for interface symmetry.
            cols, rows = self._db.fetchall(self._list_sql, {"bundle": self._bundle})
            idx = {c: i for i, c in enumerate(cols)}
            for r in rows:
                out.append(
                    RemoteFileMeta(
                        rel_path=str(r[idx.get("path", 0)]),
                        sha256=str(r[idx["sha256"]]) if "sha256" in idx and r[idx["sha256"]] is not None else None,
                        mtime=float(r[idx["updated_at"]]) if "updated_at" in idx and r[idx["updated_at"]] is not None else None,
                        size=int(r[idx["size"]]) if "size" in idx and r[idx["size"]] is not None else None,
                    )
                )
        except Exception as e:
            raise ConnectorError(f"_DBAssetSource list failed: {e}") from e
        return out

    def read_bytes(self, path: str) -> bytes:
        cols, rows = self._db.fetchall(self._fetch_sql, {"bundle": self._bundle, "path": path})
        if not rows:
            raise FileNotFoundError(f"DB asset not found: bundle={self._bundle} path={path}")
        # first column is data
        data = rows[0][0]
        if data is None:
            return b""
        return bytes(data)


class _RESTAssetSource:
    """REST-backed assets.

    REST contract (simple, explicit, no magic):
      - list: GET {base_url}{list_path}?bundle=...&prefix=...
        returns JSON: {"files": [{"path": "...", "sha256": "...", "size": 123, "mtime": 123.4}, ...]}
      - fetch: GET {base_url}{fetch_path}?bundle=...&path=...
        returns raw bytes (octet-stream)
    """

    def __init__(
        self,
        connector,
        *,
        bundle: str,
        list_path: str = "/list",
        fetch_path: str = "/fetch",
        prefix_param: str = "prefix",
    ):
        self._rest = connector
        self._bundle = bundle
        self._list_path = list_path
        self._fetch_path = fetch_path
        self._prefix_param = prefix_param

    def list_files(self, base_path: str) -> List[RemoteFileMeta]:
        out: List[RemoteFileMeta] = []
        try:
            client = self._rest.sync()
            r = client.get(self._list_path, params={"bundle": self._bundle, self._prefix_param: base_path or ""})
            r.raise_for_status()
            payload = r.json() or {}
            for f in payload.get("files") or []:
                out.append(
                    RemoteFileMeta(
                        rel_path=str(f.get("path")),
                        sha256=f.get("sha256") or None,
                        size=int(f["size"]) if f.get("size") is not None else None,
                        mtime=float(f["mtime"]) if f.get("mtime") is not None else None,
                    )
                )
        except Exception as e:
            raise ConnectorError(f"_RESTAssetSource list failed: {e}") from e
        return sorted(out, key=lambda x: x.path)

    def read_bytes(self, path: str) -> bytes:
        client = self._rest.sync()
        r = client.get(self._fetch_path, params={"bundle": self._bundle, "path": path})
        r.raise_for_status()
        return r.content



def _join_remote_path(source_type: str, base_path: str, rel: str) -> str:
    """Join base_path + rel for remote sources.

    Avoid pathlib.Path for SMB/SFTP because it can mangle separators and special
    prefixes like 'SHARE:/...'.

    - sftp: posix join (always '/')
    - smb:  join with '/' and let connector normalize to UNC
    """
    rel = rel.lstrip("/")
    if not base_path:
        return rel
    base = str(base_path).rstrip("/")

    if source_type == "sftp":
        import posixpath
        return posixpath.join(base, rel)

    if source_type == "smb":
        return f"{base}/{rel}"

    # default: behave like posix join
    return f"{base}/{rel}"

def _sha256_bytes(b: bytes) -> str:
    h = hashlib.sha256()
    h.update(b)
    return h.hexdigest()


def _mtime_sig(mtime: Optional[float]) -> int:
    """Normalize mtime into a stable integer signature.

    Many backends expose mtime with different precision. Milliseconds are a good
    compromise: stable enough for change detection while still comparable across
    platforms.
    """
    if not mtime:
        return 0
    try:
        return int(float(mtime) * 1000)
    except Exception:
        return 0


def _fingerprint(metas: Iterable[RemoteFileMeta]) -> str:
    """Stable fingerprint for a bundle."""
    parts: List[Tuple[str, str]] = []
    for m in sorted(metas, key=lambda x: x.rel_path):
        if m.sha256:
            sig = f"sha256:{m.sha256}"
        else:
            sig = f"sz:{m.size or 0}|mt_ms:{_mtime_sig(m.mtime)}"
        parts.append((m.rel_path, sig))
    raw = json.dumps(parts, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _sha256_bytes(raw)


def _snapshot_path(fp_dir: Path, fingerprint: str) -> Path:
    return fp_dir / f"{fingerprint}.json"


def _load_latest_fingerprint(fp_dir: Path) -> tuple[Optional[str], Optional[dict]]:
    """Return (fingerprint, latest_payload).

    Backward compatible: older latest.json may only contain {"fingerprint": ...}.
    """
    fp_file = fp_dir / "latest.json"
    if not fp_file.exists():
        return None, None
    try:
        payload = json.loads(fp_file.read_text("utf-8")) or {}
        fp = payload.get("fingerprint")
        return (str(fp) if fp else None), payload
    except Exception as e:
        log.warning("failed reading latest fingerprint; treating as missing", exc_info=True)
        return None, None


def _load_snapshot(fp_dir: Path, fingerprint: str) -> Optional[dict]:
    p = _snapshot_path(fp_dir, fingerprint)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text("utf-8")) or None
    except Exception as e:
        log.warning("failed reading snapshot; treating as missing", exc_info=True)
        return None


def _snapshot_file_map(snapshot: Optional[dict]) -> dict[str, dict]:
    """Map path -> {sha256,size,mtime} from a snapshot."""
    if not snapshot:
        return {}
    out: dict[str, dict] = {}
    for f in snapshot.get("files") or []:
        p = f.get("path")
        if not p:
            continue
        out[str(p)] = {
            "sha256": f.get("sha256") or None,
            "size": f.get("size") if f.get("size") is not None else None,
            "mtime": f.get("mtime") if f.get("mtime") is not None else None,
        }
    return out


def _write_latest_and_snapshot(
    *,
    fp_dir: Path,
    fingerprint: str,
    source_type: str,
    base_path: str,
    bundle_id: str,
    metas: List[RemoteFileMeta],
    extra: Optional[dict] = None,
) -> None:
    """Persist a reproducible snapshot of the bundle.

    - fingerprints/<fingerprint>.json contains the file list and per-file signatures.
    - fingerprints/latest.json points to the latest fingerprint and snapshot.
    """
    snap = {
        "version": 1,
        "bundle_id": bundle_id,
        "fingerprint": fingerprint,
        "created_at": _utc_now_iso(),
        "source": {"type": source_type, "base_path": base_path},
        "files": [
            {
                "path": m.rel_path,
                "sha256": m.sha256,
                "size": m.size,
                "mtime": m.mtime,
            }
            for m in sorted(metas, key=lambda x: x.rel_path)
        ],
    }
    if extra:
        snap.update(extra)

    snap_path = _snapshot_path(fp_dir, fingerprint)
    snap_path.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    latest = {
        "fingerprint": fingerprint,
        "snapshot": snap_path.name,
        "updated_at": _utc_now_iso(),
    }
    (fp_dir / "latest.json").write_text(json.dumps(latest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def _atomic_replace_dir(src: Path, dst: Path) -> None:
    # dst must be on same filesystem to be truly atomic.
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(src), str(dst))


def _rm_rf(p: Path) -> None:
    if not p.exists():
        return
    if p.is_symlink() or p.is_file():
        try:
            p.unlink()
        except Exception:
            pass
        return
    shutil.rmtree(p, ignore_errors=True)


def _load_profiles(env: dict[str, str]) -> dict:
    profiles_json = env.get("AETHERFLOW_PROFILES_JSON")
    profiles_file = env.get("AETHERFLOW_PROFILES_FILE")
    if profiles_json and profiles_file:
        raise ValueError("Set only one of AETHERFLOW_PROFILES_JSON or AETHERFLOW_PROFILES_FILE")
    try:
        if profiles_json:
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
    if settings.secrets_module:
        return importlib.import_module(settings.secrets_module)
    if settings.secrets_path:
        p = Path(settings.secrets_path).expanduser().resolve()
        spec = importlib.util.spec_from_file_location(f"aetherflow_set_envs_{p.stem}", p)
        if not spec or not spec.loader:
            raise RuntimeError(f"Unable to load secrets module from path: {p}")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m
    return None


def _deep_merge_dict(base: dict, override: dict) -> dict:
    """Deep-merge two dictionaries.

    Used for config/options so profile defaults don't get blown away when a
    resource overrides only one nested key.
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
    """Merge decode specs without losing nested decode paths."""
    pd = dict(profile_decode or {})
    rd = dict(resource_decode or {})
    out: dict = {}
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
            seen = set()
            deduped = []
            for item in merged:
                if item not in seen:
                    seen.add(item)
                    deduped.append(item)
            out[k] = deduped
            continue
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _deep_merge_dict(out[k], v)
            continue
        out[k] = v
    return out


def _build_resources(resources_spec: dict, *, profiles: dict, env_snapshot: dict, settings: Settings) -> dict:
    """Build resources using the unified resolver (resolution.resolve_resource)."""
    env = dict(env_snapshot)
    set_envs_mod = _load_set_envs_module(settings)

    out: Dict[str, dict] = {}
    for name, r in (resources_spec or {}).items():
        kind = r.get("kind")
        driver = r.get("driver")
        profile = r.get("profile")
        prof = profiles.get(profile, {}) if profile else {}

        config: Dict[str, Any] = _deep_merge_dict(prof.get("config", {}) or {}, r.get("config") or {})
        options: Dict[str, Any] = _deep_merge_dict(prof.get("options", {}) or {}, r.get("options") or {})
        decode: Dict[str, Any] = _merge_decode(prof.get("decode", {}) or {}, r.get("decode") or {})

        resource_dict = {"kind": kind, "driver": driver, "config": config, "options": options, "decode": decode}
        resolved = resolve_resource(resource_dict, env=env, set_envs_module=set_envs_mod)

        out[name] = {
            "kind": resolved.get("kind", kind),
            "driver": resolved.get("driver", driver),
            "config": resolved.get("config", {}),
            "options": resolved.get("options", {}),
            "decode": resolved.get("decode", decode),
        }

    return out


@dataclass
class BundleSyncResult:
    local_root: Path
    active_dir: Path
    cache_dir: Path
    fingerprints_dir: Path
    fingerprint: str
    changed: bool
    fetched_files: List[str]


@dataclass
class BundleStatus:
    bundle_id: str
    work_root: Path
    bundle_root: Path
    active_dir: Path
    cache_dir: Path
    fingerprints_dir: Path
    fingerprint: Optional[str]
    has_active: bool


def bundle_status(*, bundle_manifest: str, work_root: str | None = None, settings: Settings | None = None, env_snapshot: Dict[str, str] | None = None) -> BundleStatus:
    """Read the local bundle status for a manifest without fetching remote content."""
    env_snapshot = dict(os.environ) if env_snapshot is None else dict(env_snapshot)
    settings = settings or load_settings(env=env_snapshot)
    root = Path(work_root or settings.work_root).expanduser().resolve()

    with open(bundle_manifest, "r", encoding="utf-8") as f:
        mf = yaml.safe_load(f) or {}
        # Fail fast on typos and missing required control-plane keys.
        validate_bundle_manifest_v1(mf, bundle_manifest=bundle_manifest)

    bundle = mf.get("bundle") or {}
    bundle_id = str(bundle.get("id") or "default")

    bundle_root = root / "bundles" / bundle_id
    active_dir = bundle_root / "active"
    cache_dir = bundle_root / "cache"
    fp_dir = bundle_root / "fingerprints"

    fp, _payload = _load_latest_fingerprint(fp_dir)
    return BundleStatus(
        bundle_id=bundle_id,
        work_root=root,
        bundle_root=bundle_root,
        active_dir=active_dir,
        cache_dir=cache_dir,
        fingerprints_dir=fp_dir,
        fingerprint=fp,
        has_active=active_dir.exists(),
    )


def sync_bundle(
    *,
        bundle_manifest: str,
    work_root: str | None = None,
    settings: Settings | None = None,
    env_snapshot: Dict[str, str] | None = None,
    allow_stale: bool = False,
) -> BundleSyncResult:
    """Sync a remote bundle to a local active directory.

    Manifest YAML (minimal):

    version: 1
    bundle:
      id: prod
      source:
        type: sftp|smb|db|rest|filesystem
        resource: <resource_name>   # for non-filesystem
        base_path: /path/on/remote  # for sftp/smb/filesystem
        bundle: prod                # for db/rest
        # optional per-type settings:
        # db: list_sql/fetch_sql
        # rest: list_path/fetch_path/prefix_param
      layout:
        flows_dir: flows
        profiles_file: profiles.yaml
        plugins_dir: plugins
      entry_flow: flows/main.yaml
      fetch_policy: cache_check|always

    resources:
      sftp_main:
        kind: sftp
        driver: paramiko
        config: {host: ..., user: ..., password: ...}

    This function writes into:
      <work_root>/bundles/<bundle_id>/{active,cache,fingerprints}

    Returns the local root directory (active).
    """
    env_snapshot = dict(os.environ) if env_snapshot is None else dict(env_snapshot)
    settings = settings or load_settings(env=env_snapshot)
    root = Path(work_root or settings.work_root).expanduser().resolve()

    # Do not emit debug prints from library code; CLI has a --json mode that
    # must remain machine-readable. If you need debugging, use logging.
    with open(bundle_manifest, "r", encoding="utf-8") as f:
        mf = yaml.safe_load(f) or {}
        # Fail fast on typos and missing required control-plane keys.
        validate_bundle_manifest_v1(mf, bundle_manifest=bundle_manifest)

    bundle = mf.get("bundle") or {}
    bundle_id = bundle.get("id") or "default"
    source_cfg = bundle.get("source") or {}
    fetch_policy = (bundle.get("fetch_policy") or "cache_check").strip().lower()

    bundle_root = root / "bundles" / bundle_id
    active_dir = bundle_root / "active"
    cache_dir = bundle_root / "cache"
    fp_dir = bundle_root / "fingerprints"
    bundle_root.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    fp_dir.mkdir(parents=True, exist_ok=True)

    # Build source
    source_type = (source_cfg.get("type") or "filesystem").strip().lower()

    profiles = _load_profiles(env_snapshot)
    resources_final = _build_resources(mf.get("resources") or {}, profiles=profiles, env_snapshot=env_snapshot, settings=settings)
    ctx = RunContext(
        settings=settings,
        flow_id=f"bundle:{bundle_id}",
        run_id="bundle-sync",
        work_root=Path(str(root)),
        layout={},
        state=None,  # type: ignore
        resources=resources_final,
    )
    ctx.connectors = Connectors(ctx=ctx, resources=resources_final, settings=ctx.settings)

    base_path = source_cfg.get("base_path") or ""
    if source_type == "filesystem":
        src: BundleSource = _FilesystemSource()
        # filesystem base_path must be absolute or relative to manifest
        if base_path:
            base_path = str((Path(bundle_manifest).parent / base_path).resolve()) if not str(base_path).startswith("/") else base_path
        else:
            base_path = str(Path(bundle_manifest).parent.resolve())
    elif source_type == "sftp":
        c = ctx.connectors.sftp(source_cfg["resource"])
        src = _SFTPSource(c)
    elif source_type == "smb":
        c = ctx.connectors.smb(source_cfg["resource"])
        src = _SMBSource(c)
    elif source_type == "db":
        c = ctx.connectors.db(source_cfg["resource"])
        src = _DBAssetSource(
            c,
            bundle=str(source_cfg.get("bundle") or bundle_id),
            list_sql=source_cfg.get("list_sql"),
            fetch_sql=source_cfg.get("fetch_sql"),
        )
    elif source_type == "rest":
        c = ctx.connectors.rest(source_cfg["resource"])
        src = _RESTAssetSource(
            c,
            bundle=str(source_cfg.get("bundle") or bundle_id),
            list_path=str(source_cfg.get("list_path") or "/list"),
            fetch_path=str(source_cfg.get("fetch_path") or "/fetch"),
            prefix_param=str(source_cfg.get("prefix_param") or "prefix"),
        )
    else:
        raise ValueError(f"Unsupported source.type: {source_type}")

    strict_fingerprint = bool(source_cfg.get("strict_fingerprint") or False)

    metas: list[RemoteFileMeta] = src.list_files(base_path)

    # Load previous snapshot (if any) for incremental reuse.
    old_fp, latest_payload = _load_latest_fingerprint(fp_dir)
    old_snapshot = _load_snapshot(fp_dir, old_fp) if old_fp else None
    old_map = _snapshot_file_map(old_snapshot)

    def _read_remote_bytes(rel_path: str) -> bytes:
        """Read bytes from the configured source.

        - filesystem reads from base_path/rel
        - sftp/smb expect full remote path
        - db/rest fetch by rel
        """
        try:
            if source_type == "filesystem":
                data = Path(base_path) / rel_path
                return data.read_bytes()
            if source_type in {"sftp", "smb"}:
                remote_full = _join_remote_path(source_type, base_path, rel_path)
                return src.read_bytes(remote_full)
            return src.read_bytes(rel_path)
        except Exception as e:
            # Enrich errors for ops debugging.
            remote_full = _join_remote_path(source_type, base_path, rel_path) if source_type in {"sftp", "smb"} else rel_path
            raise RuntimeError(
                f"Failed to read remote bytes: rel={rel_path} full={remote_full} source={source_type} base_path={base_path}"
            ) from e

    # If strict_fingerprint is enabled, ensure every file has a sha256 by hashing content.
    if strict_fingerprint:
        enriched: List[RemoteFileMeta] = []
        for m in metas:
            if m.sha256:
                enriched.append(m)
                continue
            rel = m.rel_path.lstrip("/")
            b = _read_remote_bytes(rel)
            sha = _sha256_bytes(b)
            blob_path = cache_dir / sha
            if not blob_path.exists():
                blob_path.write_bytes(b)
            enriched.append(replace(m, sha256=sha))
        metas = enriched
    new_fp = _fingerprint(metas)

    if fetch_policy != "always" and old_fp == new_fp and active_dir.exists():
        return BundleSyncResult(
            local_root=active_dir,
            active_dir=active_dir,
            cache_dir=cache_dir,
            fingerprints_dir=fp_dir,
            fingerprint=new_fp,
            changed=False,
            fetched_files=[],
        )

    # Stage
    staged_parent = bundle_root / "staged"
    staged_parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="bundle_", dir=str(staged_parent)))
    fetched: List[str] = []
    file_sha: dict[str, str] = {}
    try:
        for m in metas:
            rel = m.rel_path.lstrip("/")
            dest = tmp_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)

            # Try reuse from cache without touching remote.
            sha: Optional[str] = None

            if m.sha256:
                sha = str(m.sha256)
                if not (cache_dir / sha).exists():
                    b = _read_remote_bytes(rel)
                    computed = _sha256_bytes(b)
                    if computed != sha:
                        raise ValueError(
                            f"Checksum mismatch for {rel}: expected={sha} got={computed} "
                            f"(source={source_type} base_path={base_path})"
                        )
                    (cache_dir / sha).write_bytes(b)
                    fetched.append(rel)
            else:
                # Reuse sha from previous snapshot if size+mtime match.
                prev = old_map.get(rel) or old_map.get(m.rel_path)
                prev_sha = (prev or {}).get("sha256")
                if prev_sha and prev.get("size") == m.size and _mtime_sig(prev.get("mtime")) == _mtime_sig(m.mtime):
                    if (cache_dir / str(prev_sha)).exists():
                        sha = str(prev_sha)

                if not sha:
                    b = _read_remote_bytes(rel)
                    sha = _sha256_bytes(b)
                    blob_path = cache_dir / sha
                    if not blob_path.exists():
                        blob_path.write_bytes(b)
                    fetched.append(rel)

            # Materialize
            assert sha is not None
            file_sha[rel] = sha
            shutil.copyfile(cache_dir / sha, dest)

        # validate: at least the entry_flow must exist
        entry = str(bundle.get("entry_flow") or "").strip()
        if entry:
            if not (tmp_dir / entry).exists():
                raise FileNotFoundError(f"entry_flow not found in bundle: {entry}")

        # atomic swap: replace active dir
        if active_dir.exists():
            old = bundle_root / "active.old"
            _rm_rf(old)
            os.replace(str(active_dir), str(old))
            _atomic_replace_dir(tmp_dir, active_dir)
            _rm_rf(old)
        else:
            _atomic_replace_dir(tmp_dir, active_dir)

        # Persist fingerprint snapshot (reproducibility + incremental reuse).
        metas_snapshot: List[RemoteFileMeta] = []
        for m in metas:
            rel = m.rel_path.lstrip("/")
            sha = m.sha256 or file_sha.get(rel)
            metas_snapshot.append(replace(m, sha256=str(sha) if sha else None))

        _write_latest_and_snapshot(
            fp_dir=fp_dir,
            fingerprint=new_fp,
            source_type=source_type,
            base_path=str(base_path),
            bundle_id=bundle_id,
            metas=metas_snapshot,
            extra={"strict_fingerprint": strict_fingerprint},
        )

        return BundleSyncResult(
            local_root=active_dir,
            active_dir=active_dir,
            cache_dir=cache_dir,
            fingerprints_dir=fp_dir,
            fingerprint=new_fp,
            changed=True,
            fetched_files=fetched,
        )
    except Exception as e:
        # Persist a small error report for post-mortem debugging.
        try:
            (bundle_root / "last_error.json").write_text(
                json.dumps(
                    {
                        "bundle_id": bundle_id,
                        "source_type": source_type,
                        "base_path": base_path,
                        "bundle_manifest": str(bundle_manifest),
                        "old_fingerprint": old_fp,
                        "new_fingerprint": new_fp,
                        "strict_fingerprint": strict_fingerprint,
                        "error": str(e),
                        "updated_at": _utc_now_iso(),
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        except Exception:
            pass

        _rm_rf(tmp_dir)
        if allow_stale and active_dir.exists():
            log.warning(f"Bundle sync failed, using stale active bundle_id={bundle_id}: {e}")
            return BundleSyncResult(
                local_root=active_dir,
                active_dir=active_dir,
                cache_dir=cache_dir,
                fingerprints_dir=fp_dir,
                fingerprint=old_fp or "",
                changed=False,
                fetched_files=[],
            )
        raise
