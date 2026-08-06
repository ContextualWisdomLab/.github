from pathlib import Path


def test_opencode_coverage_image_provisions_compatible_llvm_tools_before_cargo_llvm_cov():
    """Require a compatible system LLVM pair before installing cargo-llvm-cov."""
    workflow = Path(".github/workflows/opencode-review-dispatch.yml").read_text(
        encoding="utf-8"
    )

    llvm_install = workflow.index("              llvm-19 " + chr(92))
    llvm_cov_env = workflow.index("ENV LLVM_COV=/usr/bin/llvm-cov-19")
    llvm_profdata_env = workflow.index("ENV LLVM_PROFDATA=/usr/bin/llvm-profdata-19")
    llvm_check = workflow.index(
        'RUN test -x "$LLVM_COV" && test -x "$LLVM_PROFDATA"'
    )
    cargo_llvm_cov_install = workflow.index(
        "https://github.com/taiki-e/cargo-llvm-cov/releases/download/"
    )

    assert llvm_install < llvm_cov_env < llvm_check < cargo_llvm_cov_install
    assert llvm_install < llvm_profdata_env < llvm_check
