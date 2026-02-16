
from __future__ import annotations

import json
from pathlib import Path

from aetherflow.core.cli import main


def _write_bundle_tree(root: Path) -> None:
    (root / "flows").mkdir(parents=True, exist_ok=True)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    (root / "plugins").mkdir(parents=True, exist_ok=True)

    (root / "flows" / "main.yaml").write_text(
        """
version: 1
flow:
  id: demo
jobs:
  - id: job_a
    steps:
      - id: s1
        type: check_items
        inputs:
          items: []
""",
        encoding="utf-8",
    )
    (root / "profiles" / "profiles.yaml").write_text("{}", encoding="utf-8")


def test_cli_bundle_sync_filesystem(tmp_path, capsys):
    remote = tmp_path / "remote_bundle"
    _write_bundle_tree(remote)

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""
version: 1
bundle:
  id: prod
  source:
    type: filesystem
    base_path: {str(remote)}
  layout:
    flows_dir: flows
    profiles_file: profiles/profiles.yaml
    plugins_dir: plugins
  entry_flow: flows/main.yaml
  fetch_policy: cache_check
resources: {{}}
""",
        encoding="utf-8",
    )

    work_root = tmp_path / "work"

    rc1 = main(["bundle", "sync", "--bundle-manifest", str(manifest), "--work-root", str(work_root)])
    out1 = capsys.readouterr().out
    assert rc1 == 0
    assert "CHANGED:" in out1

    rc2 = main(["bundle", "sync", "--bundle-manifest", str(manifest), "--work-root", str(work_root)])
    out2 = capsys.readouterr().out
    assert rc2 == 0
    assert "UNCHANGED:" in out2


def test_cli_bundle_sync_json(tmp_path, capsys):
    remote = tmp_path / "remote_bundle"
    _write_bundle_tree(remote)

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""
version: 1
bundle:
  id: prod
  source:
    type: filesystem
    base_path: {str(remote)}
  layout:
    flows_dir: flows
    profiles_file: profiles/profiles.yaml
    plugins_dir: plugins
  entry_flow: flows/main.yaml
  fetch_policy: cache_check
resources: {{}}
""",
        encoding="utf-8",
    )

    work_root = tmp_path / "work"

    rc = main(["bundle", "sync", "--bundle-manifest", str(manifest), "--work-root", str(work_root), "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert rc == 0
    assert payload["bundle_manifest"] == str(manifest)
    assert payload["local_root"]
    assert payload["active_dir"]
    assert payload["cache_dir"]
    assert payload["fingerprints_dir"]
    assert payload["fingerprint"]


def test_cli_bundle_status(tmp_path, capsys):
    remote = tmp_path / "remote_bundle"
    _write_bundle_tree(remote)

    manifest = tmp_path / "manifest.yaml"
    manifest.write_text(
        f"""
version: 1
bundle:
  id: prod
  source:
    type: filesystem
    base_path: {str(remote)}
  layout:
    flows_dir: flows
    profiles_file: profiles/profiles.yaml
    plugins_dir: plugins
  entry_flow: flows/main.yaml
  fetch_policy: cache_check
resources: {{}}
""",
        encoding="utf-8",
    )

    work_root = tmp_path / "work"

    # Before sync: fingerprint may be none, active should be false
    rc0 = main(["bundle", "status", "--bundle-manifest", str(manifest), "--work-root", str(work_root), "--json"])
    out0 = capsys.readouterr().out
    p0 = json.loads(out0)
    assert rc0 == 0
    assert p0["bundle_id"] == "prod"
    assert p0["has_active"] is False

    # After sync: fingerprint exists and active should be true
    rc1 = main(["bundle", "sync", "--bundle-manifest", str(manifest), "--work-root", str(work_root)])
    capsys.readouterr()
    assert rc1 == 0

    rc2 = main(["bundle", "status", "--bundle-manifest", str(manifest), "--work-root", str(work_root), "--json"])
    out2 = capsys.readouterr().out
    p2 = json.loads(out2)
    assert rc2 == 0
    assert p2["has_active"] is True
    assert p2["fingerprint"]
