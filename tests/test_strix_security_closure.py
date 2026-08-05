"""Security regression contract for the central Strix dependency closure."""

from __future__ import annotations

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_strix_direct_dependencies_select_advisory_fixed_releases() -> None:
    """The trusted Strix input must select the reviewed fixed security floor."""
    requirements = (
        _REPOSITORY_ROOT / "requirements-strix-ci.txt"
    ).read_text(encoding="utf-8").splitlines()

    assert "aiohttp==3.14.3" in requirements
    assert "cryptography==50.0.0" in requirements
    assert "aiohttp==3.14.1" not in requirements
    assert "cryptography==49.0.0" not in requirements


def test_strix_hash_lock_matches_the_reviewed_security_closure() -> None:
    """The immutable lock must contain fixed aiohttp, cryptography, and PyOpenSSL."""
    lock = (
        _REPOSITORY_ROOT / "requirements-strix-ci-hashes.txt"
    ).read_text(encoding="utf-8")

    assert "aiohttp==3.14.3 \\\n" in lock
    assert "cryptography==50.0.0 \\\n" in lock
    assert "pyopenssl==26.4.0 \\\n" in lock
    assert "aiohttp==3.14.1 \\\n" not in lock
    assert "cryptography==49.0.0 \\\n" not in lock
