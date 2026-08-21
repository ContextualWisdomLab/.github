"""Permanent contract for the trusted asyncio coverage toolchain."""

from __future__ import annotations

import asyncio
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import pytest_asyncio


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_HELPER_PATH = _REPOSITORY_ROOT / "scripts/ci/ensure_opencode_asyncio_toolchain.sh"
_REVIEW_REQUIREMENTS_PATH = _REPOSITORY_ROOT / "requirements-opencode-review-ci.txt"
_REVIEW_HASH_LOCK_PATH = _REPOSITORY_ROOT / "requirements-opencode-review-ci-hashes.txt"
_DISPATCH_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-review-dispatch.yml"
)
_QUALITY_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/trusted-uv-materializer-quality-ci.yml"
)
_PINNED_ASYNCIO_PLUGIN = "pytest-asyncio==1.4.0"
_PINNED_TYPING_EXTENSIONS = "typing-extensions==4.16.0"
_HELPER_IMPORT_LINE = (
    "import coverage, interrogate, pytest, pytest_asyncio, pytest_cov"
)
_HASHED_DISPATCH_IMPORT_LINE = "import coverage, interrogate, pytest, pytest_cov"
_SHA256_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")


def _lock_entry(package_name: str) -> str:
    """Return the generated lock stanza for one pinned package."""

    collected: list[str] = []
    capturing = False
    for line in _REVIEW_HASH_LOCK_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{package_name}=="):
            capturing = True
        if not capturing:
            continue
        collected.append(line)
        if not line.rstrip().endswith("\\"):
            break
    assert collected, f"missing lock entry for {package_name}"
    return "\n".join(collected)


def test_opencode_coverage_toolchain_supports_repository_asyncio_tests() -> None:
    """Keep the trusted coverage sandbox able to execute marked asyncio tests."""

    requirements = _REVIEW_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    hash_lock = _REVIEW_HASH_LOCK_PATH.read_text(encoding="utf-8")
    helper = _HELPER_PATH.read_text(encoding="utf-8")

    assert _PINNED_ASYNCIO_PLUGIN in requirements
    assert _PINNED_ASYNCIO_PLUGIN in hash_lock
    assert _HELPER_IMPORT_LINE in helper
    assert len(_SHA256_HASH.findall(_lock_entry("pytest-asyncio"))) >= 1


def test_opencode_hash_lock_is_installable_by_python_security_runtime() -> None:
    """Keep the Python 3.12 audit runtime's conditional dependency pinned."""

    requirements = _REVIEW_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    hash_lock = _REVIEW_HASH_LOCK_PATH.read_text(encoding="utf-8")

    assert _PINNED_TYPING_EXTENSIONS in requirements
    assert _PINNED_TYPING_EXTENSIONS in hash_lock
    assert len(_SHA256_HASH.findall(_lock_entry("typing-extensions"))) >= 1


def test_asyncio_helper_executes_the_trusted_import() -> None:
    """Run the helper import so a missing plugin fails this quality gate."""

    helper = _HELPER_PATH.read_text(encoding="utf-8")
    assert _HELPER_PATH.stat().st_mode & stat.S_IXUSR
    assert "python3 -I" in helper
    assert _HELPER_IMPORT_LINE in helper
    completed = subprocess.run(
        ["bash", str(_HELPER_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    assert pytest_asyncio.__name__ == "pytest_asyncio"


def test_hashed_dispatch_smoke_is_not_rewritten_for_asyncio() -> None:
    """Keep the review-agent key blob from carrying the coverage-plugin import."""

    dispatch = _DISPATCH_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert _HASHED_DISPATCH_IMPORT_LINE in dispatch
    assert _HELPER_IMPORT_LINE not in dispatch


def test_quality_ci_executes_asyncio_helper_after_hash_lock_install() -> None:
    """Keep the helper on the installed lock path, not as unread documentation."""

    workflow = _QUALITY_WORKFLOW_PATH.read_text(encoding="utf-8")
    install_index = workflow.index(
        "python -m pip install --disable-pip-version-check --require-hashes "
        "-r requirements-opencode-review-ci-hashes.txt"
    )
    helper_index = workflow.index(
        "bash scripts/ci/ensure_opencode_asyncio_toolchain.sh"
    )
    assert helper_index > install_index
    assert workflow.count('"scripts/ci/ensure_opencode_asyncio_toolchain.sh"') == 2
    assert workflow.count('"tests/test_opencode_asyncio_toolchain_contract.py"') == 2


@pytest.mark.asyncio
async def test_marked_coroutine_executes_under_pinned_plugin() -> None:
    """Prove a marked coroutine actually runs instead of failing collection."""

    await asyncio.sleep(0)
    assert pytest_asyncio.__name__ == "pytest_asyncio"


def test_pinned_plugin_collects_a_marked_coroutine_like_a_buyer_suite(
    tmp_path: Path,
) -> None:
    """Reproduce the downstream failure: marked async tests must collect and pass."""

    sample = tmp_path / "test_buyer_async_suite.py"
    sample.write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.asyncio\n"
        "async def test_marked_coroutine_reaches_an_assertion() -> None:\n"
        "    assert True\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(sample), "-q"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "async def functions are not natively supported" not in result.stdout
    assert "async def functions are not natively supported" not in result.stderr
