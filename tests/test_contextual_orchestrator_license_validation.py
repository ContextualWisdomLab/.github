"""Regression tests for pre-install contextual-orchestrator license validation."""

from __future__ import annotations

import pathlib

import pytest

from scripts.ci import validate_contextual_orchestrator_licenses as validator


def test_parse_locked_packages_accepts_hash_continuations() -> None:
    """The validator reads only exact package pins from pip-compile output."""
    lock = (
        "demo-package==1.2.3 \\\n"
        "    --hash=sha256:" + "a" * 64 + "\n# via demo\n"
    )
    assert validator.parse_locked_packages(lock) == (("demo-package", "1.2.3"),)


def test_parse_locked_packages_rejects_unpinned_or_empty_input() -> None:
    """Editable, URL, and empty lock inputs fail closed before any query."""
    with pytest.raises(validator.LicenseValidationError):
        validator.parse_locked_packages("demo-package>=1\n")
    with pytest.raises(validator.LicenseValidationError):
        validator.parse_locked_packages("# comment only\n")


def test_source_license_requires_approved_mit_evidence(tmp_path: pathlib.Path) -> None:
    """A checkout must carry a recognizable approved source license."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    assert validator.validate_source_license(tmp_path) == "MIT"
    (tmp_path / "LICENSE").write_text("LGPL-3.0-only\n", encoding="utf-8")
    with pytest.raises(validator.LicenseValidationError):
        validator.validate_source_license(tmp_path)
