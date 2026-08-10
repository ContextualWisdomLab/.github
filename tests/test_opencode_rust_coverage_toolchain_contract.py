"""Permanent contract for the trusted Rust LLVM coverage toolchain."""

from __future__ import annotations

import re
from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW_PATH = _REPOSITORY_ROOT / ".github/workflows/opencode-review-dispatch.yml"
_QUALITY_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-rust-coverage-toolchain-quality-ci.yml"
)
_LLVM_COV_PATH = "/usr/bin/llvm-cov-19"
_LLVM_PROFDATA_PATH = "/usr/bin/llvm-profdata-19"


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
    llvm_cov_environment = workflow.index(f"ENV LLVM_COV={_LLVM_COV_PATH}")
    llvm_profdata_environment = workflow.index(
        f"ENV LLVM_PROFDATA={_LLVM_PROFDATA_PATH}"
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


def test_isolated_runtime_receives_reviewed_llvm_constants() -> None:
    """Require exact LLVM 19 path propagation through the Docker boundary."""

    workflow = _workflow_text()
    docker_run = workflow.index("docker run --rm")
    llvm_cov_binding = workflow.index(
        f"--env LLVM_COV={_LLVM_COV_PATH}", docker_run
    )
    llvm_profdata_binding = workflow.index(
        f"--env LLVM_PROFDATA={_LLVM_PROFDATA_PATH}", docker_run
    )
    coverage_image = workflow.index('"$coverage_tool_image"', docker_run)

    assert docker_run < llvm_cov_binding < llvm_profdata_binding < coverage_image


def test_isolated_runtime_revalidates_llvm_tools_before_coverage() -> None:
    """Require reviewed-path equality and executable checks before Rust coverage."""

    workflow = _workflow_text()
    docker_run = workflow.index("docker run --rm")
    toolchain_start = workflow.index("ensure_rust_toolchain() {", docker_run)
    toolchain_end = workflow.index("rust_coverage_manifests() {", toolchain_start)
    toolchain = workflow[toolchain_start:toolchain_end]
    cargo_coverage_invocation = workflow.index("cargo llvm-cov", toolchain_end)
    llvm_cov_checks = _all_positions(workflow, 'test -x "$LLVM_COV"')
    llvm_profdata_checks = _all_positions(workflow, 'test -x "$LLVM_PROFDATA"')

    assert f'"${{LLVM_COV:-}}" != "{_LLVM_COV_PATH}"' in toolchain
    assert f'"${{LLVM_PROFDATA:-}}" != "{_LLVM_PROFDATA_PATH}"' in toolchain
    assert docker_run < llvm_cov_checks[-1] < cargo_coverage_invocation
    assert docker_run < llvm_profdata_checks[-1] < cargo_coverage_invocation


def test_quality_workflow_watched_paths_resolve_to_repository_files() -> None:
    """Every exact-path trigger in the permanent quality workflow must exist."""

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
    for relative_path in watched_paths:
        assert (_REPOSITORY_ROOT / relative_path).is_file(), relative_path
