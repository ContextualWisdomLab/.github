"""Permanent contract for the trusted Rust LLVM coverage toolchain."""

from __future__ import annotations

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_HELPER_PATH = _REPOSITORY_ROOT / "scripts/ci/ensure_rust_llvm19.sh"
_QUALITY_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-rust-coverage-toolchain-quality-ci.yml"
)
_LLVM_COV_PATH = "/usr/bin/llvm-cov-19"
_LLVM_PROFDATA_PATH = "/usr/bin/llvm-profdata-19"


def _helper_text() -> str:
    """Return the reviewed LLVM 19 runtime-boundary helper."""

    return _HELPER_PATH.read_text(encoding="utf-8")


def test_trusted_rust_coverage_image_provisions_verified_llvm_19_tools() -> None:
    """Require explicit compatible LLVM 19 tools in the reviewed helper."""

    helper = _helper_text()
    assert f'LLVM_COV_PATH="${{LLVM_COV_PATH:-{_LLVM_COV_PATH}}}"' in helper
    assert (
        f'LLVM_PROFDATA_PATH="${{LLVM_PROFDATA_PATH:-{_LLVM_PROFDATA_PATH}}}"'
        in helper
    )
    assert 'test -x "${LLVM_COV:-}"' in helper
    assert 'test -x "${LLVM_PROFDATA:-}"' in helper


def test_isolated_runtime_receives_reviewed_llvm_constants() -> None:
    """Require exact LLVM 19 path constants in the helper contract."""

    helper = _helper_text()
    assert _LLVM_COV_PATH in helper
    assert _LLVM_PROFDATA_PATH in helper
    assert "unversioned" not in helper


def test_isolated_runtime_revalidates_llvm_tools_before_coverage() -> None:
    """Require reviewed-path equality and executable checks before coverage."""

    helper = _helper_text()
    assert f'"${{LLVM_COV:-}}" != "$LLVM_COV_PATH"' in helper
    assert f'"${{LLVM_PROFDATA:-}}" != "$LLVM_PROFDATA_PATH"' in helper
    assert "exit 1" in helper


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
