from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import yaml
import pytest

from aetherflow.core.bundles import sync_bundle


def _write_text(p: Path, txt: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(txt, encoding="utf-8")


def test_bundle_sync_filesystem(tmp_path: Path, monkeypatch):
    # Create a "remote" tree (filesystem source)
    remote = tmp_path / "remote"
    _write_text(remote / "profiles.yaml", "profiles: {}\n")
    _write_text(remote / "plugins" / "x.py", "# user plugin\n")
    _write_text(
        remote / "flows" / "demo.yaml",
        """
flow:
  id: demo
  workspace: {root: /tmp/work, layout: {}}
  state: {path: :memory:}
jobs: []
""".lstrip(),
    )

    manifest = tmp_path / "bundle.yml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "bundle": {
                    "id": "fs",
                    "source": {"type": "filesystem", "base_path": str(remote)},
                    "layout": {"profiles_file": "profiles.yaml", "plugins_dir": "plugins"},
                    "entry_flow": "flows/demo.yaml",
                },
                "resources": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AETHERFLOW_WORK_ROOT", str(tmp_path / "work"))
    res1 = sync_bundle(bundle_manifest=str(manifest))
    assert res1.changed is True
    # Fingerprint snapshot is persisted for reproducibility/incremental reuse.
    fp_dir = Path(os.environ["AETHERFLOW_WORK_ROOT"]) / "bundles" / "fs" / "fingerprints"
    assert (fp_dir / "latest.json").exists()
    import json
    latest = json.loads((fp_dir / "latest.json").read_text("utf-8")) or {}
    assert latest.get("fingerprint")
    snap_name = latest.get("snapshot")
    assert snap_name
    assert (fp_dir / snap_name).exists()
    assert (res1.local_root / "flows" / "demo.yaml").exists()
    assert (res1.local_root / "plugins" / "x.py").exists()
    assert (res1.local_root / "profiles.yaml").exists()

    # Second sync: unchanged -> no fetch
    res2 = sync_bundle(bundle_manifest=str(manifest))
    assert res2.changed is False

    # Modify remote -> should fetch again
    _write_text(remote / "plugins" / "x.py", "# changed\n")
    res3 = sync_bundle(bundle_manifest=str(manifest))
    assert res3.changed is True
    # Incremental: only the changed file should be fetched.
    assert res3.fetched_files == ["plugins/x.py"]


def test_bundle_sync_db_sqlite(tmp_path: Path, monkeypatch):
    db_path = tmp_path / "assets.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE assets(
          bundle TEXT NOT NULL,
          path TEXT NOT NULL,
          sha256 TEXT,
          data BLOB,
          updated_at REAL,
          size INTEGER,
          PRIMARY KEY(bundle, path)
        )
        """
    )
    conn.commit()

    bundle_id = "prod"

    # insert minimal flow yaml
    flow_bytes = (
        """
flow:
  id: demo
  workspace: {root: /tmp/work, layout: {}}
  state: {path: :memory:}
jobs: []
""".lstrip().encode("utf-8")
    )
    cur.execute(
        "INSERT INTO assets(bundle, path, sha256, data, updated_at, size) VALUES(?,?,?,?,?,?)",
        (bundle_id, "flows/demo.yaml", None, flow_bytes, 1.0, len(flow_bytes)),
    )
    # profiles
    prof = b"profiles: {}\n"
    cur.execute(
        "INSERT INTO assets(bundle, path, sha256, data, updated_at, size) VALUES(?,?,?,?,?,?)",
        (bundle_id, "profiles.yaml", None, prof, 1.0, len(prof)),
    )
    conn.commit()
    conn.close()

    manifest = tmp_path / "bundle_db.yml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "bundle": {
                    "id": "db",
                    "source": {"type": "db", "resource": "db1", "bundle": bundle_id},
                    "layout": {"profiles_file": "profiles.yaml"},
                    "entry_flow": "flows/demo.yaml",
                },
                    "resources": {
                        "db1": {
                            "kind": "db",
                            "driver": "sqlite3",
                            "config": {"path": str(db_path)},
                        }
                    },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AETHERFLOW_WORK_ROOT", str(tmp_path / "work"))
    res = sync_bundle(bundle_manifest=str(manifest))
    assert res.changed is True
    assert (res.local_root / "flows" / "demo.yaml").exists()
    assert (res.local_root / "profiles.yaml").exists()


def test_strict_fingerprint_detects_content_change_even_if_mtime_same(tmp_path: Path, monkeypatch):
    remote = tmp_path / "remote"
    _write_text(remote / "profiles.yaml", "profiles: {}\n")
    _write_text(remote / "flows" / "demo.yaml", "flow: {id: demo}\njobs: []\n")
    _write_text(remote / "plugins" / "x.py", "AAAA\n")

    # Freeze mtime so a content change wouldn't be detected by (size,mtime) signature.
    fixed_time = 1700000000
    os.utime(remote / "plugins" / "x.py", (fixed_time, fixed_time))

    manifest = tmp_path / "bundle_strict.yml"
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "bundle": {
                    "id": "strict",
                    "source": {"type": "filesystem", "base_path": str(remote), "strict_fingerprint": True},
                    "layout": {"profiles_file": "profiles.yaml", "plugins_dir": "plugins"},
                    "entry_flow": "flows/demo.yaml",
                },
                "resources": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AETHERFLOW_WORK_ROOT", str(tmp_path / "work"))
    res1 = sync_bundle(bundle_manifest=str(manifest))
    assert res1.changed is True

    # Change content but keep same mtime.
    _write_text(remote / "plugins" / "x.py", "BBBB\n")
    os.utime(remote / "plugins" / "x.py", (fixed_time, fixed_time))

    res2 = sync_bundle(bundle_manifest=str(manifest))
    assert res2.changed is True



def test_smb_share_override_path_parsing():
    # Pure unit test: no smbclient import (we don't call _register / IO).
    from aetherflow.core.builtins.connectors import SMBClient
    from aetherflow.core.connectors.base import ConnectorInit

    init = ConnectorInit(
        name="smb1",
        kind="smb",
        driver="smbclient",
        config={"server": "fileserver", "share": "DATA", "username": "u", "password": "p"},
        options={},
        ctx=None,
    )
    c = SMBClient(init)

    # Default share from config
    assert c._path("dir/file.txt") == r"\\fileserver\DATA\dir\file.txt"

    # Override share via SHARE:/ prefix
    assert c._path("BUNDLES:/aetherflow/bundles/prod.zip") == r"\\fileserver\BUNDLES\aetherflow\bundles\prod.zip"


def test_join_remote_path_does_not_mangle_share_prefix():
    from aetherflow.core.bundles import _join_remote_path

    assert _join_remote_path("smb", "BUNDLES:/a/b", "c.txt") == "BUNDLES:/a/b/c.txt"
    assert _join_remote_path("smb", "/a/b", "c.txt") == "/a/b/c.txt"
    assert _join_remote_path("sftp", "/a/b", "c.txt").endswith("/a/b/c.txt")
    # Trailing/leading slashes
    assert _join_remote_path("smb", "BUNDLES:/a/b/", "/c.txt") == "BUNDLES:/a/b/c.txt"
    assert _join_remote_path("sftp", "/a/b/", "/c.txt").endswith("/a/b/c.txt")


def test_manifest_validation_unknown_keys_fails_fast(tmp_path: Path, monkeypatch):
    remote = tmp_path / "remote_bundle"
    (remote / "flows").mkdir(parents=True)
    (remote / "flows" / "main.yaml").write_text("flow: {}\n", encoding="utf-8")
    (remote / "profiles.yaml").write_text("{}\n", encoding="utf-8")

    manifest = tmp_path / "m.yaml"
    # Typo: fetch_polciy (unknown key) should fail fast
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "bundle": {
                    "id": "t",
                    "source": {"type": "filesystem", "base_path": str(remote)},
                    "layout": {"profiles_file": "profiles.yaml", "plugins_dir": "plugins"},
                    "entry_flow": "flows/main.yaml",
                    "fetch_polciy": "cache_check",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AETHERFLOW_WORK_ROOT", str(tmp_path / "work"))

    with pytest.raises(ValueError) as e:
        sync_bundle(bundle_manifest=str(manifest))
    assert "Unknown bundle keys" in str(e.value)


def test_manifest_validation_missing_required_keys(tmp_path: Path, monkeypatch):
    remote = tmp_path / "remote_bundle"
    remote.mkdir(parents=True)
    (remote / "flows").mkdir(parents=True)
    (remote / "flows" / "main.yaml").write_text("flow: {}\n", encoding="utf-8")

    manifest = tmp_path / "m.yaml"
    # Missing bundle.layout.profiles_file must fail fast
    manifest.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "bundle": {
                    "id": "t",
                    "source": {"type": "filesystem", "base_path": str(remote)},
                    "layout": {"plugins_dir": "plugins"},
                    "entry_flow": "flows/main.yaml",
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AETHERFLOW_WORK_ROOT", str(tmp_path / "work"))

    with pytest.raises(ValueError) as e:
        sync_bundle(bundle_manifest=str(manifest))
    assert "bundle.layout.profiles_file" in str(e.value)
