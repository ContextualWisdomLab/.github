"""Contract tests for the trusted Rust coverage toolchain."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")


def test_trusted_coverage_image_provisions_and_verifies_llvm_19() -> None:
    """Require verified LLVM 19 executables before cargo-llvm-cov installation."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "llvm-19" in workflow
    assert "LLVM_COV=/usr/bin/llvm-cov-19" in workflow
    assert "LLVM_PROFDATA=/usr/bin/llvm-profdata-19" in workflow
    llvm_check = workflow.index(
        'RUN test -x "$LLVM_COV" && test -x "$LLVM_PROFDATA"'
    )
    cargo_install = workflow.index(
        "https://github.com/taiki-e/cargo-llvm-cov/releases/download/v0.8.7/"
    )
    assert llvm_check < cargo_install


def test_rust_coverage_runtime_preserves_explicit_llvm_paths() -> None:
    """Keep cargo-llvm-cov bound to the image-verified LLVM 19 tools."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "--env LLVM_COV=/usr/bin/llvm-cov-19" in workflow
    assert "--env LLVM_PROFDATA=/usr/bin/llvm-profdata-19" in workflow
    assert 'test -x "$LLVM_COV"' in workflow
    assert 'test -x "$LLVM_PROFDATA"' in workflow
