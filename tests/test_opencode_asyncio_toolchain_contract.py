"""Permanent contract for the trusted asyncio coverage toolchain."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_HELPER_PATH = _REPOSITORY_ROOT / "scripts/ci/ensure_opencode_asyncio_toolchain.sh"
_REVIEW_REQUIREMENTS_PATH = _REPOSITORY_ROOT / "requirements-opencode-review-ci.txt"
_REVIEW_HASH_LOCK_PATH = _REPOSITORY_ROOT / "requirements-opencode-review-ci-hashes.txt"
_QUALITY_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/trusted-uv-materializer-quality-ci.yml"
)
_IMPORT_LINE = (
    "import coverage, interrogate, pytest, pytest_asyncio, pytest_cov"
)
_PYTEST_ASYNCIO_HASHES = (
    "933ca923a23075a87fb7070c0ec272a6848489824d887c85c812670932835aa1",
    "c6c0d2259945122819f171a32ecea2c349ead889ee28176caaf492143424be42",
)
_TYPING_EXTENSIONS_HASHES = (
    "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
    "dc983d19a509c94dba722ee6abd33940f7c05a89e243c47e907eb4db6f1a43e5",
)


def test_opencode_coverage_toolchain_supports_repository_asyncio_tests() -> None:
    """Keep the trusted coverage sandbox able to execute marked asyncio tests."""

    requirements = _REVIEW_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    hash_lock = _REVIEW_HASH_LOCK_PATH.read_text(encoding="utf-8")
    helper = _HELPER_PATH.read_text(encoding="utf-8")

    assert "pytest-asyncio==1.4.0" in requirements
    assert "pytest-asyncio==1.4.0" in hash_lock
    assert _IMPORT_LINE in helper
    for digest in _PYTEST_ASYNCIO_HASHES:
        assert digest in hash_lock


def test_opencode_hash_lock_is_installable_by_python_security_runtime() -> None:
    """Keep the Python 3.12 audit runtime's conditional dependency pinned."""

    requirements = _REVIEW_REQUIREMENTS_PATH.read_text(encoding="utf-8")
    hash_lock = _REVIEW_HASH_LOCK_PATH.read_text(encoding="utf-8")

    assert "typing-extensions==4.16.0" in requirements
    assert "typing-extensions==4.16.0" in hash_lock
    for digest in _TYPING_EXTENSIONS_HASHES:
        assert digest in hash_lock


def test_asyncio_helper_is_valid_fail_closed_bash() -> None:
    """Reject a helper that cannot be parsed before quality CI executes it."""

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to syntax-check the asyncio helper")

    result = subprocess.run(
        [bash, "-n", str(_HELPER_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


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
    assert workflow.count('"requirements-opencode-review-ci.txt"') == 2
    assert "tests/test_opencode_asyncio_toolchain_contract.py" in workflow


def test_pinned_plugin_collects_a_marked_coroutine_like_a_buyer_suite(
    tmp_path: Path,
) -> None:
    """Reproduce the downstream failure: marked async tests must collect and pass."""

    pytest.importorskip("pytest_asyncio")
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
