"""Contracts for the central Rust bindgen and Python 3.10 coverage toolchains."""

from __future__ import annotations

from pathlib import Path


OPENCODE_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
DIAGNOSTICS_WORKFLOW = Path(
    ".github/workflows/opencode-coverage-diagnostics-ci.yml"
)
PYTHON310_LOCK = Path("requirements-opencode-python310-ci-hashes.txt")
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

    assert workflow.count(f'      - "{CONTRACT_PATH}"') == 2
    assert f"            {CONTRACT_PATH} " + chr(92) in workflow
    assert f"            {CONTRACT_PATH}" in workflow


def test_python310_runtime_uses_one_hash_locked_tomli_backport() -> None:
    """Require the Python 3.10 TOML backport through a dedicated immutable lock."""
    workflow = DIAGNOSTICS_WORKFLOW.read_text(encoding="utf-8")
    lock = PYTHON310_LOCK.read_text(encoding="utf-8")

    assert "requirements-opencode-python310-ci-hashes.txt" in workflow
    assert "--require-hashes" in workflow
    assert "--only-binary=:all:" in workflow
    assert "tomli==2.4.1" in lock
    assert (
        "sha256:0d85819802132122da43cb86656f8d1f8c6587d54ae7dcaf30e90533028b49fe"
        in lock
    )
    assert "http://" not in lock
    assert "https://" not in lock
