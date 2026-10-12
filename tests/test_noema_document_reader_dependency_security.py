"""Keep the Noema document reader above known vulnerable transitive releases."""

from __future__ import annotations

import json
from functools import total_ordering
from pathlib import Path
import re

import pytest


_NPM_IDENTIFIER_RE = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
_NPM_VERSION_RE = re.compile(
    rf"^(?P<major>0|[1-9][0-9]*)\.(?P<minor>0|[1-9][0-9]*)\."
    rf"(?P<patch>0|[1-9][0-9]*)(?:-(?P<prerelease>{_NPM_IDENTIFIER_RE}"
    rf"(?:\.{_NPM_IDENTIFIER_RE})*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


@total_ordering
class NpmVersion:
    """One strict npm SemVer value with final releases above prereleases."""

    def __init__(self, value: str) -> None:
        """Parse one complete npm package-lock version string."""
        match = _NPM_VERSION_RE.fullmatch(value)
        if match is None:
            raise ValueError(f"invalid npm SemVer: {value!r}")
        self._release = tuple(int(match.group(key)) for key in ("major", "minor", "patch"))
        prerelease = match.group("prerelease")
        self._prerelease = None if prerelease is None else tuple(
            int(part) if part.isdecimal() else part for part in prerelease.split(".")
        )

    def __eq__(self, other: object) -> bool:
        """Compare npm precedence without considering build metadata."""
        return isinstance(other, NpmVersion) and (
            self._release,
            self._prerelease,
        ) == (other._release, other._prerelease)

    def __lt__(self, other: object) -> bool:
        """Order prerelease identifiers according to the npm SemVer contract."""
        if not isinstance(other, NpmVersion):
            return NotImplemented
        if self._release != other._release:
            return self._release < other._release
        if self._prerelease is None or other._prerelease is None:
            return self._prerelease is not None and other._prerelease is None
        for left, right in zip(self._prerelease, other._prerelease):
            if left == right:
                continue
            if type(left) is int and type(right) is str:
                return True
            if type(left) is str and type(right) is int:
                return False
            return left < right
        return len(self._prerelease) < len(other._prerelease)


def _parse_npm_version(value: str) -> NpmVersion:
    """Return one strict npm SemVer value for a package-lock security floor."""
    return NpmVersion(value)


LOCK_FILE = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "noema-document-reader"
    / "package-lock.json"
)
PACKAGE_FILE = LOCK_FILE.with_name("package.json")


def test_numeric_npm_prerelease_is_older_than_the_fixed_final() -> None:
    """Keep npm numeric prereleases below their corresponding final release."""
    assert _parse_npm_version("3.1.8-1") < _parse_npm_version("3.1.8")


def test_npm_semver_preserves_prerelease_and_build_precedence() -> None:
    """Numeric identifiers sort before strings and build metadata changes no precedence."""
    assert _parse_npm_version("3.1.8-1") < _parse_npm_version("3.1.8-alpha")
    assert _parse_npm_version("3.1.8+build.1") == _parse_npm_version("3.1.8+build.2")


@pytest.mark.parametrize("version", ["3.1", "03.1.8", "3.1.8-01", "3.1.8-", "3.1.8+bad_"])
def test_invalid_npm_semver_cannot_pass_a_security_floor(version: str) -> None:
    """Reject malformed package-lock versions instead of assigning them precedence."""
    with pytest.raises(ValueError, match="invalid npm SemVer"):
        _parse_npm_version(version)


def _locked_versions(lock_data: dict[str, object], package_name: str) -> list[NpmVersion]:
    """Return every hoisted or nested locked npm release for one package."""
    package_records = lock_data["packages"]
    assert isinstance(package_records, dict)
    path_suffix = f"node_modules/{package_name}"
    release_versions: list[NpmVersion] = []
    for package_path, package_data in package_records.items():
        if package_path != path_suffix and not package_path.endswith(f"/{path_suffix}"):
            continue
        assert isinstance(package_data, dict)
        release_versions.append(_parse_npm_version(package_data["version"]))
    return release_versions


def test_document_reader_transitives_include_security_fixes() -> None:
    """Reject releases affected by the September 2026 URI and IP advisories."""
    lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
    for package_name, minimum_version in {
        "fast-uri": _parse_npm_version("3.1.8"),
        "ip-address": _parse_npm_version("10.7.1"),
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
    assert _locked_versions(lock_data, "ip-address") == [
        _parse_npm_version("10.7.1"),
        _parse_npm_version("10.7.0"),
    ]


def test_prerelease_does_not_satisfy_final_security_minimum() -> None:
    """Treat a prerelease of the fixed version as older than the final release."""
    lock_data = {
        "packages": {
            "node_modules/fast-uri": {"version": "3.1.8-beta.1"},
        }
    }

    locked_versions = _locked_versions(lock_data, "fast-uri")

    assert locked_versions == [_parse_npm_version("3.1.8-beta.1")]
    assert not all(version >= _parse_npm_version("3.1.8") for version in locked_versions)


def test_document_reader_source_owns_transitive_security_fixes() -> None:
    """Require source overrides so lock regeneration preserves the repair."""
    package_data = json.loads(PACKAGE_FILE.read_text(encoding="utf-8"))

    assert package_data["overrides"] == {
        "fast-uri": "3.1.8",
        "ip-address": "10.7.1",
    }
