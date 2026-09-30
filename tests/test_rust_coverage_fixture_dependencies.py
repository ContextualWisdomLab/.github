"""Security contracts for the offline Rust coverage dependency fixture."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "coverage-cargo"


def test_coverage_fixture_uses_patched_pyo3_release() -> None:
    """Keep the fixture manifest and lock on the reviewed PyO3 0.29.2 release."""
    manifest = (FIXTURE_ROOT / "Cargo.toml").read_text(encoding="utf-8")
    lock = (FIXTURE_ROOT / "Cargo.lock").read_text(encoding="utf-8")

    assert 'pyo3 = { version = "=0.29.2"' in manifest
    assert 'name = "pyo3"\nversion = "0.29.2"' in lock
