"""Contracts for the central Rust bindgen and libclang coverage toolchain."""

from __future__ import annotations

from pathlib import Path


OPENCODE_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
DIAGNOSTICS_WORKFLOW = Path(
    ".github/workflows/opencode-coverage-diagnostics-ci.yml"
)
CONTRACT_PATH = "tests/test_opencode_libclang_toolchain_contract.py"


def test_opencode_coverage_image_provisions_version_aligned_libclang() -> None:
    """Require libclang 19 before bindgen-backed Rust coverage can execute."""
    workflow = OPENCODE_WORKFLOW.read_text(encoding="utf-8")

    llvm_package = "              llvm-19 " + chr(92)
    libclang_package = "              libclang-19-dev " + chr(92)
    libclang_environment = "ENV LIBCLANG_PATH=/usr/lib/llvm-19/lib"
    library_probe = 'find "$LIBCLANG_PATH" -maxdepth 1'
    library_pattern = "-name 'libclang.so*'"
    cargo_llvm_cov_download = (
        "https://github.com/taiki-e/cargo-llvm-cov/releases/download/"
    )

    assert llvm_package in workflow
    assert libclang_package in workflow
    assert libclang_environment in workflow
    assert library_probe in workflow
    assert library_pattern in workflow
    assert workflow.index(libclang_package) < workflow.index(library_probe)
    assert workflow.index(library_probe) < workflow.index(cargo_llvm_cov_download)


def test_permanent_diagnostics_workflow_runs_the_libclang_contract() -> None:
    """Keep the libclang contract in permanent exact-head diagnostics CI."""
    workflow = DIAGNOSTICS_WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count(f'- "{CONTRACT_PATH}"') == 2
    assert f"            {CONTRACT_PATH} " + chr(92) in workflow
    assert f"            {CONTRACT_PATH}" in workflow
