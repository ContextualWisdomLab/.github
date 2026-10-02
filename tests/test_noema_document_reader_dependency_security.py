"""Keep the Noema document reader above known vulnerable transitive releases."""

from __future__ import annotations

import json
from pathlib import Path

from packaging.version import Version

LOCK_FILE = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "noema-document-reader"
    / "package-lock.json"
)
PACKAGE_FILE = LOCK_FILE.with_name("package.json")


def _locked_versions(lock_data: dict[str, object], package_name: str) -> list[tuple[int, ...]]:
    """Return every hoisted or nested locked release for one package."""
    package_records = lock_data["packages"]
    assert isinstance(package_records, dict)
    path_suffix = f"node_modules/{package_name}"
    release_versions: list[tuple[int, ...]] = []
    for package_path, package_data in package_records.items():
        if package_path != path_suffix and not package_path.endswith(f"/{path_suffix}"):
            continue
        assert isinstance(package_data, dict)
        release_versions.append(tuple(int(part) for part in package_data["version"].split(".")))
    return release_versions


def test_document_reader_transitives_include_security_fixes() -> None:
    """Reject releases affected by the September 2026 URI and IP advisories."""
    lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    for package_name, minimum_version in {
        "fast-uri": (3, 1, 8),
        "ip-address": (10, 7, 1),
    }.items():
        locked_versions = _locked_versions(lock_data, package_name)
        assert locked_versions
        assert all(version >= minimum_version for version in locked_versions)


def test_nested_vulnerable_transitive_is_detected() -> None:
    """Do not let a patched hoisted package hide a vulnerable nested copy."""
    lock_data = {
        "packages": {
            "node_modules/ip-address": {"version": "10.7.1"},
            "node_modules/parent/node_modules/ip-address": {"version": "10.7.0"},
        }
    }
    assert _locked_versions(lock_data, "ip-address") == [(10, 7, 1), (10, 7, 0)]


def test_prerelease_does_not_satisfy_final_security_minimum() -> None:
    """Treat a prerelease of the fixed version as older than the final release."""
    lock_data = {
        "packages": {
            "node_modules/fast-uri": {"version": "3.1.8-beta.1"},
        }
    }

    locked_versions = _locked_versions(lock_data, "fast-uri")

    assert locked_versions == [Version("3.1.8-beta.1")]
    assert not all(version >= Version("3.1.8") for version in locked_versions)


def test_document_reader_source_owns_transitive_security_fixes() -> None:
    """Require source overrides so lock regeneration preserves the repair."""
    package_data = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))

    assert package_data["overrides"] == {
        "fast-uri": "3.1.8",
        "ip-address": "10.7.1",
    }
