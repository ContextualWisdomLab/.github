"""Permanent contract for the trusted Rust LLVM coverage toolchain."""

from __future__ import annotations

import re
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/opencode-review-dispatch.yml"


def _workflow_text() -> str:
    """Return the authoritative OpenCode review-dispatch workflow text."""

    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def _all_positions(text: str, fragment: str) -> list[int]:
    """Return every start position of ``fragment`` in ``text``."""

    return [match.start() for match in re.finditer(re.escape(fragment), text)]


def test_trusted_rust_coverage_image_provisions_verified_llvm_19_tools() -> None:
    """Require explicit compatible LLVM tools before cargo-llvm-cov installation."""

    workflow = _workflow_text()

    llvm_package = workflow.index("llvm-19")
    llvm_cov_environment = workflow.index(
        "ENV LLVM_COV=/usr/bin/llvm-cov-19"
    )
    llvm_profdata_environment = workflow.index(
        "ENV LLVM_PROFDATA=/usr/bin/llvm-profdata-19"
    )
    llvm_cov_checks = _all_positions(workflow, 'test -x "$LLVM_COV"')
    llvm_profdata_checks = _all_positions(workflow, 'test -x "$LLVM_PROFDATA"')
    cargo_llvm_cov_archive = workflow.index(
        "cargo-llvm-cov-x86_64-unknown-linux-musl.tar.gz"
    )

    assert len(llvm_cov_checks) >= 2
    assert len(llvm_profdata_checks) >= 2
    assert (
        llvm_package
        < llvm_cov_environment
        < llvm_profdata_environment
        < llvm_cov_checks[0]
        < llvm_profdata_checks[0]
        < cargo_llvm_cov_archive
    )


def test_isolated_runtime_receives_and_revalidates_explicit_llvm_paths() -> None:
    """Require isolated Rust coverage to fail closed on missing LLVM executables."""

    workflow = _workflow_text()
    cargo_coverage_invocation = workflow.index("cargo llvm-cov")
    llvm_cov_checks = _all_positions(workflow, 'test -x "$LLVM_COV"')
    llvm_profdata_checks = _all_positions(workflow, 'test -x "$LLVM_PROFDATA"')

    assert re.search(
        r"(?:-e|--env(?:=|\s+))\s*LLVM_COV(?:=|\s)",
        workflow,
    )
    assert re.search(
        r"(?:-e|--env(?:=|\s+))\s*LLVM_PROFDATA(?:=|\s)",
        workflow,
    )
    assert llvm_cov_checks[-1] < cargo_coverage_invocation
    assert llvm_profdata_checks[-1] < cargo_coverage_invocation
