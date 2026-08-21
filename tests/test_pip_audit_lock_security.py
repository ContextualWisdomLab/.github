"""Regression contract for the hash-locked pip-audit toolchain."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_pip_audit_toolchain_uses_fixed_pip_release() -> None:
    """Keep the OSV-repaired pip release explicit in source and lock files."""
    source = (REPOSITORY_ROOT / "requirements-pip-audit-ci.txt").read_text(
        encoding="utf-8"
    )
    lock = (REPOSITORY_ROOT / "requirements-pip-audit-ci-hashes.txt").read_text(
        encoding="utf-8"
    )

    assert "pip==26.2.1" in source
    assert "pip==26.1.2" not in source
    assert "pip==26.2.1" in lock
    assert "pip==26.1.2" not in lock
    assert "sha256:71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e" in lock
    assert "sha256:f6ad667e89a1fe78046c8f13232b247200f5258d7828f3f7883d660878e0813f" in lock
