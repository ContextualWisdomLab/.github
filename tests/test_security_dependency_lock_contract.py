"""Regression contracts for vulnerability-scanned Python CI locks."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _locked_versions(path: str) -> dict[str, str]:
    """Return normalized package versions from one uv-generated lock."""
    versions: dict[str, str] = {}
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        if "==" not in line or line.startswith((" ", "#")):
            continue
        name, version = line.split("==", 1)
        versions[name.casefold()] = version.rstrip(" \\")
    return versions


def test_pip_audit_runtime_uses_patched_urllib3() -> None:
    """The auditing tool itself must not retain the vulnerable urllib3 runtime."""
    direct = (ROOT / "requirements-pip-audit-ci.txt").read_text(encoding="utf-8")
    locked = _locked_versions("requirements-pip-audit-ci-hashes.txt")

    assert "urllib3==2.8.0" in direct.splitlines()
    assert locked["urllib3"] == "2.8.0"


def test_strix_runtime_uses_patched_security_overrides() -> None:
    """The overridden Strix lock must pin every advisory repair from the gate."""
    overrides = _locked_versions("requirements-strix-ci-overrides.txt")
    locked = _locked_versions("requirements-strix-ci-hashes.txt")
    expected = {
        "litellm": "1.94.3",
        "pyjwt": "2.15.0",
        "pypdf": "6.19.0",
        "urllib3": "2.8.0",
    }

    assert {name: overrides[name] for name in expected} == expected
    assert {name: locked[name] for name in expected} == expected
