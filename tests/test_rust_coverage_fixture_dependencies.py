"""Security contracts for the offline Rust coverage dependency fixture."""

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = REPOSITORY_ROOT / "tests" / "fixtures" / "coverage-cargo"


def test_coverage_fixture_uses_patched_pyo3_release() -> None:
    """Keep the fixture manifest and lock on the reviewed PyO3 0.29.2 release."""
    manifest = tomllib.loads(
        (FIXTURE_ROOT / "Cargo.toml").read_text(encoding="utf-8")
    )
    cargo_lock = tomllib.loads(
        (FIXTURE_ROOT / "Cargo.lock").read_text(encoding="utf-8")
    )
    pyo3_packages = [
        package_entry
        for package_entry in cargo_lock["package"]
        if package_entry["name"] == "pyo3"
    ]

    assert manifest["dependencies"]["pyo3"]["version"] == "=0.29.2"
    assert {package_entry["version"] for package_entry in pyo3_packages} == {
        "0.29.2"
    }
    assert len(pyo3_packages) == 1
