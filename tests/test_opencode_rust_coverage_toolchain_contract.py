"""Permanent contract for the trusted Rust LLVM coverage toolchain."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_HELPER_PATH = _REPOSITORY_ROOT / "scripts/ci/ensure_rust_llvm19.sh"
_DISPATCH_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-review-dispatch.yml"
)
_QUALITY_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-rust-coverage-toolchain-quality-ci.yml"
)
_NIM_CONTRACT_PATH = (
    _REPOSITORY_ROOT / "tests/test_pr_review_autofix_nvidia_nim_contract.py"
)
_LLVM_COV_PATH = "/usr/bin/llvm-cov-19"
_LLVM_PROFDATA_PATH = "/usr/bin/llvm-profdata-19"
_BLOB_SHA_PATTERN = re.compile(
    r'^REVIEW_DISPATCH_BLOB_SHA = "([0-9a-f]{40})"$',
    re.MULTILINE,
)


def _helper_text() -> str:
    """Return the reviewed LLVM 19 runtime-boundary helper."""

    return _HELPER_PATH.read_text(encoding="utf-8")


def _dispatch_text() -> str:
    """Return the trusted coverage-image and sandbox workflow."""

    return _DISPATCH_WORKFLOW_PATH.read_text(encoding="utf-8")


def _run_helper(
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    """Execute the helper with a caller-supplied environment."""

    return subprocess.run(
        ["bash", str(_HELPER_PATH)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_trusted_coverage_image_provisions_verified_llvm_19_tools() -> None:
    """Require Debian llvm-19 and build-time executability in trusted source."""

    dispatch = _dispatch_text()
    assert "              llvm-19 \\\n" in dispatch
    assert f"ENV LLVM_COV={_LLVM_COV_PATH}\n" in dispatch
    assert f"ENV LLVM_PROFDATA={_LLVM_PROFDATA_PATH}\n" in dispatch
    assert 'RUN test -x "$LLVM_COV"\n' in dispatch
    assert 'RUN test -x "$LLVM_PROFDATA"\n' in dispatch


def test_isolated_runtime_receives_reviewed_llvm_constants() -> None:
    """Require exact LLVM 19 path constants at the Docker sandbox boundary."""

    dispatch = _dispatch_text()
    helper = _helper_text()
    assert f"              --env LLVM_COV={_LLVM_COV_PATH} \\\n" in dispatch
    assert f"              --env LLVM_PROFDATA={_LLVM_PROFDATA_PATH} \\\n" in dispatch
    assert _LLVM_COV_PATH in helper
    assert _LLVM_PROFDATA_PATH in helper
    assert "unversioned" not in helper
    assert "${LLVM_COV_PATH:-" not in helper
    assert "${LLVM_PROFDATA_PATH:-" not in helper


def test_isolated_runtime_revalidates_llvm_tools_before_coverage() -> None:
    """Require the trusted toolchain guard to fail closed before cargo llvm-cov."""

    dispatch = _dispatch_text()
    helper = _helper_text()
    assert f'[ "${{LLVM_COV:-}}" != "{_LLVM_COV_PATH}" ]' in dispatch
    assert f'[ "${{LLVM_PROFDATA:-}}" != "{_LLVM_PROFDATA_PATH}" ]' in dispatch
    assert 'test -x "$LLVM_COV"' in dispatch
    assert 'test -x "$LLVM_PROFDATA"' in dispatch
    assert "networkless coverage runtime did not preserve the reviewed LLVM 19" in dispatch
    assert f'LLVM_COV_PATH="{_LLVM_COV_PATH}"' in helper
    assert f'LLVM_PROFDATA_PATH="{_LLVM_PROFDATA_PATH}"' in helper
    assert '"${LLVM_COV:-}" != "$LLVM_COV_PATH"' in helper
    assert '"${LLVM_PROFDATA:-}" != "$LLVM_PROFDATA_PATH"' in helper
    assert "exit 1" in helper


def test_quality_workflow_watches_the_trusted_dispatch_workflow() -> None:
    """Guard drift in the hashed review-dispatch blob must retrigger this contract."""

    quality_workflow = _QUALITY_WORKFLOW_PATH.read_text(encoding="utf-8")
    assert (
        '      - ".github/workflows/opencode-review-dispatch.yml"\n' in quality_workflow
    )
    assert (
        '      - "tests/test_pr_review_autofix_nvidia_nim_contract.py"\n'
        in quality_workflow
    )


def test_review_dispatch_blob_sha_stays_paired_with_trusted_workflow() -> None:
    """A dispatch.yml rewrite must update the independent review-dispatch blob pin."""

    nim_contract = _NIM_CONTRACT_PATH.read_text(encoding="utf-8")
    match = _BLOB_SHA_PATTERN.search(nim_contract)
    assert match is not None
    hashed = subprocess.run(
        ["git", "hash-object", str(_DISPATCH_WORKFLOW_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert hashed.stdout.strip() == match.group(1)


def test_quality_workflow_watched_paths_resolve_to_repository_files() -> None:
    """Every watched path and its documented runtime contract must exist."""

    quality_workflow = _QUALITY_WORKFLOW_PATH.read_text(encoding="utf-8")
    watched_section = quality_workflow.split("    paths:\n", 1)[1].split(
        "\n\npermissions:\n", 1
    )[0]
    watched_paths = [
        line.strip()[2:].strip('"')
        for line in watched_section.splitlines()
        if line.strip().startswith("- ")
    ]

    assert watched_paths
    assert ".github/workflows/opencode-review-dispatch.yml" in watched_paths
    assert "tests/test_pr_review_autofix_nvidia_nim_contract.py" in watched_paths
    for relative_path in watched_paths:
        assert (_REPOSITORY_ROOT / relative_path).is_file(), relative_path
    doctoring = (
        _REPOSITORY_ROOT
        / "docs/doctoring/opencode-rust-coverage-runtime-boundary.md"
    ).read_text(encoding="utf-8")
    assert "/usr/bin/llvm-cov-19" in doctoring
    assert "/usr/bin/llvm-profdata-19" in doctoring
    assert "unversioned `llvm-cov`" in doctoring
    assert "fails closed" in doctoring


def test_helper_fails_closed_when_reviewed_paths_are_unbound() -> None:
    """A coverage runtime without the reviewed LLVM env cannot produce evidence."""

    result = _run_helper({"PATH": os.environ.get("PATH", "/usr/bin")})

    assert result.returncode == 1
    assert _LLVM_COV_PATH in result.stderr
    assert _LLVM_PROFDATA_PATH in result.stderr


def test_helper_fails_closed_when_caller_overrides_the_reviewed_paths(
    tmp_path: Path,
) -> None:
    """Caller-selected LLVM_COV_PATH values cannot retarget the reviewed tools."""

    decoy = tmp_path / "llvm-cov-decoy"
    decoy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    decoy.chmod(decoy.stat().st_mode | stat.S_IXUSR)
    result = _run_helper(
        {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "LLVM_COV": str(decoy),
            "LLVM_PROFDATA": str(decoy),
            "LLVM_COV_PATH": str(decoy),
            "LLVM_PROFDATA_PATH": str(decoy),
        }
    )

    assert result.returncode == 1
    assert _LLVM_COV_PATH in result.stderr


@pytest.mark.skipif(
    not Path(_LLVM_COV_PATH).is_file() or not Path(_LLVM_PROFDATA_PATH).is_file(),
    reason="reviewed LLVM 19 tools are not installed on this host",
)
def test_helper_admits_the_reviewed_llvm_19_tools_when_present() -> None:
    """The helper accepts only the reviewed executable paths when they exist."""

    if not os.access(_LLVM_COV_PATH, os.X_OK) or not os.access(
        _LLVM_PROFDATA_PATH, os.X_OK
    ):
        pytest.skip("reviewed LLVM 19 tools are not executable on this host")

    result = _run_helper(
        {
            "PATH": os.environ.get("PATH", "/usr/bin"),
            "LLVM_COV": _LLVM_COV_PATH,
            "LLVM_PROFDATA": _LLVM_PROFDATA_PATH,
        }
    )

    assert result.returncode == 0
    assert result.stderr == ""
