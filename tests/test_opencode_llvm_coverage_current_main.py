from pathlib import Path


_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
_QUALITY_WORKFLOW = Path(
    ".github/workflows/opencode-coverage-toolchain-quality-ci.yml"
)


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


def test_opencode_toolchain_quality_workflow_is_exact_head_bound_and_offline():
    """Require the fast contract job to stay exact-head and dependency-free."""
    workflow = _QUALITY_WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("  exact-head-contract:")
    end = workflow.index("  full-repository-quality:", start)
    fast_job = workflow[start:end]

    assert "ref: ${{ github.event.pull_request.head.sha }}" in fast_job
    assert "persist-credentials: false" in fast_job
    assert (
        'test "$(git rev-parse HEAD)" = '
        '"${{ github.event.pull_request.head.sha }}"' in fast_job
    )
    assert "importlib.util.spec_from_file_location" in fast_job
    assert "python3 -m compileall -q" in fast_job
    assert "pip install" not in fast_job
    assert "uv sync" not in fast_job


def test_opencode_toolchain_quality_runs_full_hash_locked_repository_suite():
    """Require a separate exact-head full-suite job with 100% quality gates."""
    workflow = _QUALITY_WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("  full-repository-quality:")
    full_job = workflow[start:]

    assert "needs: exact-head-contract" in full_job
    assert "ref: ${{ github.event.pull_request.head.sha }}" in full_job
    assert "persist-credentials: false" in full_job
    assert (
        'test "$(git rev-parse HEAD)" = '
        '"${{ github.event.pull_request.head.sha }}"' in full_job
    )
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in full_job
    assert 'python-version: "3.14"' in full_job
    assert "--require-hashes -r requirements-opencode-review-ci-hashes.txt" in full_job
    assert "python -m coverage run -m pytest tests -q" in full_job
    assert "python -m coverage report" in full_job
    assert "python -m interrogate --fail-under 100 scripts/ci" in full_job
    assert "python -m compileall -q scripts/ci tests" in full_job
