"""Regression contracts for security-scanned dependency fixtures."""

from __future__ import annotations

from pathlib import Path
import tomllib


ROOT = Path(__file__).resolve().parents[1]
CARGO_FIXTURE = ROOT / "tests/fixtures/coverage-cargo"


def test_coverage_cargo_fixture_uses_patched_pyo3_release() -> None:
    """The Trivy-scanned Cargo fixture must not retain vulnerable pyo3 releases."""
    manifest = tomllib.loads((CARGO_FIXTURE / "Cargo.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((CARGO_FIXTURE / "Cargo.lock").read_text(encoding="utf-8"))
    packages = {
        (package["name"], package["version"])
        for package in lock["package"]
    }

    assert manifest["dependencies"]["pyo3"]["version"] == "=0.29.0"
    assert ("pyo3", "0.29.0") in packages
    assert ("pyo3", "0.22.6") not in packages
