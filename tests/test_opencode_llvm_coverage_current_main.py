from pathlib import Path


_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")


def test_opencode_coverage_image_provisions_compatible_llvm_tools_before_cargo_llvm_cov():
    """Require a compatible system LLVM pair before installing cargo-llvm-cov."""
    workflow = _WORKFLOW.read_text(encoding="utf-8")

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


def test_low_privilege_coverage_wrappers_isolate_ambient_git_configuration():
    """Require system and global Git isolation before the safe-directory overlay."""
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    boundaries = (
        ("run_and_capture", "run_r_package_testthat"),
        ("run_r_package_testthat", "run_and_capture_advisory"),
        ("run_and_capture_advisory", "trusted_git"),
    )

    for wrapper_name, next_name in boundaries:
        start = workflow.index(f"          {wrapper_name}() {{")
        end = workflow.index(f"          {next_name}() {{", start)
        wrapper = workflow[start:end]

        no_system = wrapper.index("GIT_CONFIG_NOSYSTEM=1")
        no_global = wrapper.index("GIT_CONFIG_GLOBAL=/dev/null")
        safe_directory_count = wrapper.index("GIT_CONFIG_COUNT=1")

        assert no_system < no_global < safe_directory_count
        assert wrapper.count("GIT_CONFIG_NOSYSTEM=1") == 1
        assert wrapper.count("GIT_CONFIG_GLOBAL=/dev/null") == 1
