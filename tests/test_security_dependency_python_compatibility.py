"""Regression for Python 3.10 TOML parser compatibility."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_CONTRACT = ROOT / "tests/test_security_dependency_fixture_contract.py"


def test_dependency_fixture_contract_falls_back_to_tomli() -> None:
    """The fixture contract must remain importable on supported Python 3.10."""
    source = DEPENDENCY_CONTRACT.read_text(encoding="utf-8")

    assert "try:\n    import tomllib" in source
    assert "except ModuleNotFoundError:\n    import tomli as tomllib" in source
