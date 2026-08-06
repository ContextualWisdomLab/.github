"""Permanent contract for the trusted Rust LLVM coverage toolchain."""

from __future__ import annotations

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/opencode-review-dispatch.yml"


def _workflow_text() -> str:
    """Return the authoritative OpenCode review-dispatch workflow text."""

    return _WORKFLOW_PATH.read_text(encoding="utf-8")


def _workflow_section(workflow: str, start: str, end: str) -> str:
    """Return one named shell-function section from the workflow."""

    section_start = workflow.index(start)
    section_end = workflow.index(end, section_start)
    return workflow[section_start:section_end]


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
    executable_validation = workflow.index(
        'RUN test -x "$LLVM_COV" && test -x "$LLVM_PROFDATA"'
    )
    cargo_llvm_cov_archive = workflow.index(
        "cargo-llvm-cov-x86_64-unknown-linux-musl.tar.gz"
    )

    assert workflow.count("ENV LLVM_COV=") == 1
    assert workflow.count("ENV LLVM_PROFDATA=") == 1
    assert (
        llvm_package
        < llvm_cov_environment
        < llvm_profdata_environment
        < executable_validation
        < cargo_llvm_cov_archive
    )


def test_image_llvm_bindings_survive_the_low_privilege_runtime_wrapper() -> None:
    """Require the immutable image bindings to reach untrusted Rust tests."""

    workflow = _workflow_text()
    runtime_wrapper = _workflow_section(
        workflow,
        "          run_and_capture() {",
        "          run_r_package_testthat() {",
    )

    # Dockerfile ENV values persist in containers instantiated from the image.
    # The low-privilege wrapper must therefore preserve, rather than clear or
    # replace, those reviewed versioned LLVM bindings.
    assert any(
        line.strip() == f"env {chr(92)}"
        for line in runtime_wrapper.splitlines()
    )
    assert "env -i" not in runtime_wrapper
    assert "-u LLVM_COV" not in runtime_wrapper
    assert "-u LLVM_PROFDATA" not in runtime_wrapper
    assert "LLVM_COV=" not in runtime_wrapper
    assert "LLVM_PROFDATA=" not in runtime_wrapper
