"""Permanent contract for the trusted asyncio coverage toolchain."""

from __future__ import annotations

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_HELPER_PATH = _REPOSITORY_ROOT / "scripts/ci/ensure_opencode_asyncio_toolchain.sh"
_REVIEW_REQUIREMENTS_PATH = _REPOSITORY_ROOT / "requirements-opencode-review-ci.txt"
_REVIEW_HASH_LOCK_PATH = _REPOSITORY_ROOT / "requirements-opencode-review-ci-hashes.txt"
_IMPORT_LINE = (
    "import coverage, interrogate, pytest, pytest_asyncio, pytest_cov"
)


def test_opencode_coverage_toolchain_supports_repository_asyncio_tests() -> None:
    """Keep the trusted coverage sandbox able to execute marked asyncio tests."""

    requirements = _REVIEW_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    hash_lock = _REVIEW_HASH_LOCK_PATH.read_text(encoding="utf-8")
    helper = _HELPER_PATH.read_text(encoding="utf-8")

    assert "pytest-asyncio==1.4.0" in requirements
    assert "pytest-asyncio==1.4.0" in hash_lock
    assert _IMPORT_LINE in helper


def test_opencode_hash_lock_is_installable_by_python_security_runtime() -> None:
    """Keep the Python 3.12 audit runtime's conditional dependency pinned."""

    requirements = _REVIEW_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    hash_lock = _REVIEW_HASH_LOCK_PATH.read_text(encoding="utf-8")

    assert "typing-extensions==4.16.0" in requirements
    assert "typing-extensions==4.16.0" in hash_lock
