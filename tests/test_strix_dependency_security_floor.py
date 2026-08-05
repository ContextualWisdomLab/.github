"""Contracts for the security-reviewed Strix dependency lock."""

from __future__ import annotations

from pathlib import Path


def test_strix_requirements_pin_reviewed_security_versions() -> None:
    """The canonical input pins versions that close the August 2026 advisories."""
    requirements = Path("requirements-strix-ci.txt").read_text(encoding="utf-8")
    assert "aiohttp==3.14.3\n" in requirements
    assert "cryptography==50.0.0\n" in requirements
    assert "aiohttp==3.14.1\n" not in requirements
    assert "cryptography==49.0.0\n" not in requirements


def test_strix_hash_lock_matches_the_canonical_security_pins() -> None:
    """The generated lock retains the reviewed direct security pins."""
    lock = Path("requirements-strix-ci-hashes.txt").read_text(encoding="utf-8")
    assert "aiohttp==3.14.3 \\\n" in lock
    assert "cryptography==50.0.0 \\\n" in lock
    assert "aiohttp==3.14.1 \\\n" not in lock
    assert "cryptography==49.0.0 \\\n" not in lock
