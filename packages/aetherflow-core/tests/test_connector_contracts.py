from __future__ import annotations

import inspect

import pytest

from aetherflow.core.registry.connectors import get_connector, list_connectors


def _sig_params(fn):
    return list(inspect.signature(fn).parameters.keys())


@pytest.mark.contract
def test_archive_connectors_implement_zip_contract() -> None:
    """Lock the duck-typed contract for resources.kind=archive.

    Plugin authors can add new archive drivers, but they MUST provide the same
    callable surface area as core expects.
    """

    failures: list[str] = []
    for key in list_connectors():
        kind, driver = key.split(":", 1)
        if kind != "archive":
            continue
        cls = get_connector(kind, driver)

        if not hasattr(cls, "create_zip"):
            failures.append(f"archive:{driver} missing create_zip")
            continue
        if not hasattr(cls, "extract_zip"):
            failures.append(f"archive:{driver} missing extract_zip")
            continue

        create_params = _sig_params(getattr(cls, "create_zip"))
        extract_params = _sig_params(getattr(cls, "extract_zip"))

        # NOTE: We only lock parameter NAMES here (duck-type). Types are enforced
        # by runtime behavior + unit tests.
        expected_create = [
            "self",
            "output",
            "files",
            "base_dir",
            "password",
            "compression",
            "overwrite",
        ]
        expected_extract = [
            "self",
            "archive",
            "dest_dir",
            "password",
            "overwrite",
            "members",
        ]

        if create_params != expected_create:
            failures.append(
                f"archive:{driver} create_zip signature mismatch: {create_params} != {expected_create}"
            )
        if extract_params != expected_extract:
            failures.append(
                f"archive:{driver} extract_zip signature mismatch: {extract_params} != {expected_extract}"
            )

    assert not failures, "\n".join(failures)


@pytest.mark.contract
@pytest.mark.parametrize("kind", ["sftp", "smb"])
def test_file_connectors_implement_min_contract(kind: str) -> None:
    """Lock the minimal connector contract for file-ish remotes.

    These are the methods core uses across bundles/steps.
    """

    required = {
        "read_bytes",
        "write_bytes",
        "upload",
        "download",
        "list",
        "delete",
        "mkdir",
        "mkdir_recursive",
        "delete_recursive",
    }

    failures: list[str] = []
    for key in list_connectors():
        k, driver = key.split(":", 1)
        if k != kind:
            continue
        cls = get_connector(k, driver)
        missing = sorted([m for m in required if not hasattr(cls, m)])
        if missing:
            failures.append(f"{kind}:{driver} missing: {missing}")

    # If there are no connectors of that kind loaded, that's fine (optional deps).
    assert not failures, "\n".join(failures)
