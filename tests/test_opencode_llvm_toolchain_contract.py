"""Contracts for permanent OpenCode LLVM and Python 3.10 coverage tooling."""

from __future__ import annotations

from pathlib import Path


OPENCODE_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
DIAGNOSTICS_WORKFLOW = Path(
    ".github/workflows/opencode-coverage-diagnostics-ci.yml"
)
PYTHON310_LOCK = Path("requirements-opencode-python310-ci-hashes.txt")
CONTRACT_PATH = "tests/test_opencode_llvm_toolchain_contract.py"
TRANSIENT_WORKFLOWS = (
    ".github/workflows/one-shot-pr759-apply-libclang.yml",
    ".github/workflows/one-shot-pr759-final-merge.yml",
    ".github/workflows/one-shot-pr759-libclang-final.yml",
)
TRANSIENT_SCRIPTS = (
    "scripts/ci/apply_pr759_libclang_final.py",
    "scripts/ci/apply_pr759_libclang_runtime_only.py",
)


def test_opencode_coverage_image_provisions_versioned_llvm_tools() -> None:
    """Require the reviewed LLVM 19 tools before Rust coverage can execute."""
    workflow = OPENCODE_WORKFLOW.read_text(encoding="utf-8")

    llvm_package = "              llvm-19 " + chr(92)
    llvm_cov_environment = "ENV LLVM_COV=/usr/bin/llvm-cov-19"
    llvm_profdata_environment = "ENV LLVM_PROFDATA=/usr/bin/llvm-profdata-19"
    executable_probe = 'RUN test -x "$LLVM_COV" && test -x "$LLVM_PROFDATA"'
    cargo_llvm_cov_download = (
        "https://github.com/taiki-e/cargo-llvm-cov/releases/download/"
    )

    assert llvm_package in workflow
    assert llvm_cov_environment in workflow
    assert llvm_profdata_environment in workflow
    assert executable_probe in workflow
    assert workflow.index(llvm_package) < workflow.index(executable_probe)
    assert workflow.index(executable_probe) < workflow.index(cargo_llvm_cov_download)


def test_permanent_diagnostics_workflow_runs_the_llvm_contract() -> None:
    """Keep the LLVM contract in permanent exact-head diagnostics CI."""
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


def test_transient_pr759_branch_writers_are_absent() -> None:
    """Forbid one-shot write workflows, encoded patches, and apply helpers."""
    for path in (*TRANSIENT_WORKFLOWS, *TRANSIENT_SCRIPTS):
        assert not Path(path).exists(), path
    assert not Path(".github/pr759-final-patch").exists()
