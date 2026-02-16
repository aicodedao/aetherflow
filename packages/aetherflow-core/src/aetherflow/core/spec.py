from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Set, Literal, Optional, Type

from pydantic import BaseModel, Field, RootModel
from pydantic.config import ConfigDict

# ---------------------------------------------------------------------------
# Workspace / State / Locks
# ---------------------------------------------------------------------------

CleanupPolicy = Literal["on_success", "always", "never"]
LockScope = Literal["none", "job", "flow"]


class WorkspaceSpec(BaseModel):
    root: str = "/tmp/work"
    cleanup_policy: CleanupPolicy = "on_success"
    layout: Dict[str, str] = Field(
        default_factory=lambda: {
            "artifacts": "artifacts",
            "scratch": "scratch",
            "manifests": "manifests",
        }
    )


class StateSpec(BaseModel):
    backend: Literal["sqlite", "file"] = "sqlite"
    path: str = "/tmp/state/aetherflow.sqlite"


class LocksSpec(BaseModel):
    scope: LockScope = "job"
    ttl_seconds: int = 3600


# ---------------------------------------------------------------------------
# Flow / Jobs / Steps
# ---------------------------------------------------------------------------


class FlowMetaSpec(BaseModel):
    id: str
    description: Optional[str] = None
    workspace: WorkspaceSpec = Field(default_factory=WorkspaceSpec)
    state: StateSpec = Field(default_factory=StateSpec)
    locks: LocksSpec = Field(default_factory=LocksSpec)


class ResourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    driver: str
    profile: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)

    # Optional decode hints used by the resolver / runtime.
    decode: Dict[str, Any] = Field(default_factory=dict)


class StepSpec(BaseModel):
    id: str
    type: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    # If the step reports SKIPPED (via StepResult.status), the runner can skip the
    # rest of the job when this is set.
    on_no_data: Optional[Literal["skip_job"]] = None
    # Optional mapping to expose selected values as job outputs (for downstream job gating).
    # Values are rendered with the same Jinja renderer used for step inputs.
    outputs: Dict[str, Any] = Field(default_factory=dict)


class JobSpec(BaseModel):
    id: str
    description: Optional[str] = None
    depends_on: List[str] = Field(default_factory=list)
    # Optional condition to run the job. If false, the job is marked SKIPPED.
    # Expression is evaluated against a limited safe context.
    when: Optional[str] = None
    steps: List[StepSpec]


class FlowSpec(BaseModel):
    version: int = 1
    flow: FlowMetaSpec
    resources: Dict[str, ResourceSpec] = Field(default_factory=dict)
    jobs: List[JobSpec]


# ---------------------------------------------------------------------------
# Profiles
# ---------------------------------------------------------------------------


class ProfileSpec(BaseModel):
    """Profile mapping: env -> resource config/options.

    Notes:
      - profiles are NOT an env layer; they map env keys into connector config/options.
      - only keys here are supported; unknown keys should be treated as typos.
    """

    model_config = ConfigDict(extra="forbid")

    config: Dict[str, Any] = Field(default_factory=dict)
    options: Dict[str, Any] = Field(default_factory=dict)
    decode: Dict[str, Any] = Field(default_factory=dict)


class ProfilesFileSpec(RootModel[Dict[str, ProfileSpec]]):
    """profiles.yaml root schema: mapping name -> ProfileSpec."""


# ---------------------------------------------------------------------------
# Bundles
# ---------------------------------------------------------------------------

BundleArchiveDriverType = Literal["pyzipper", "zipfile", "os", "external"]
BundleSourceType = Literal["filesystem", "sftp", "smb", "db", "rest"]
BundleFetchPolicy = Literal["cache_check", "always"]


class BundleLayoutSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flows_dir: str = None
    profiles_file: str = None
    plugins_dir: str = None


class BundleSourceSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: BundleSourceType = "filesystem"
    resource: Optional[str] = None
    base_path: Optional[str] = None
    bundle: Optional[str] = None

    # db
    list_sql: Optional[str] = None
    fetch_sql: Optional[str] = None

    # rest
    list_path: Optional[str] = None
    fetch_path: Optional[str] = None
    prefix_param: Optional[str] = None

    # fingerprint
    strict_fingerprint: Optional[bool] = None


class BundleSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    source: BundleSourceSpec
    layout: BundleLayoutSpec = Field(default_factory=BundleLayoutSpec)
    entry_flow: str
    fetch_policy: BundleFetchPolicy = "cache_check"


class BundleManifestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = 1
    mode: Optional[str] = None
    bundle: BundleSpec
    resources: Dict[str, ResourceSpec] = Field(default_factory=dict)
    paths: Dict[str, Any] = Field(default_factory=dict)
    zip_drivers: Set[BundleArchiveDriverType] = Field(
        default_factory=lambda: {"pyzipper", "zipfile"}
    )
    env_files: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Env files
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EnvFileSpec:
    """Spec for loading env vars from disk.

    Supported types:
      - dotenv: KEY=VALUE lines, UTF-8, '#' comments.
      - json: top-level object {"KEY": "VALUE", ...}
      - dir: directory where each file name is a key; file content is the value.

    Notes:
      - All loaded values are coerced to strings.
      - No shell expansion/magic.
    """

    type: str
    path: str
    optional: bool = False
    prefix: str = ""


# ---------------------------------------------------------------------------
# Connectors
# ---------------------------------------------------------------------------


@dataclass
class ConnectorSpec:
    kind: str
    driver: str
    cls: Type


@dataclass(frozen=True)
class RemoteFileMeta:
    """Metadata used to build a bundle fingerprint.

    Not all remotes can provide sha256 cheaply (SFTP/SMB). In that case
    we fingerprint with (path, size, mtime). When sha256 is available,
    it is preferred.
    """
    rel_path: Optional[str] = None
    path: Optional[str] = None
    name: Optional[str] = None
    is_dir: Optional[bool] = False
    size: Optional[int] = None
    mtime: Optional[float] = None
    sha256: Optional[str] = None


__all__ = [
    # workspace/state/locks
    "WorkspaceSpec",
    "StateSpec",
    "LocksSpec",
    "CleanupPolicy",
    "LockScope",
    # flow
    "FlowMetaSpec",
    "ResourceSpec",
    "StepSpec",
    "JobSpec",
    "FlowSpec",
    # profiles
    "ProfileSpec",
    "ProfilesFileSpec",
    # bundles
    "BundleLayoutSpec",
    "BundleSourceSpec",
    "BundleSpec",
    "BundleManifestSpec",
    "BundleSourceType",
    "BundleFetchPolicy",
    # env
    "EnvFileSpec",
    # connectors
    "ConnectorSpec",
    "RemoteFileMeta"
]
