"""Apply the reviewed PR 759 libclang coverage-image repair exactly once."""

from __future__ import annotations

from pathlib import Path


DISPATCH_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
DIAGNOSTICS_PATH = Path(".github/workflows/opencode-coverage-diagnostics-ci.yml")
TEST_PATH = Path("tests/test_opencode_libclang_toolchain_contract.py")
CHANGELOG_PATH = Path("CHANGELOG.md")
DOCTORING_PATH = Path("docs/doctoring/opencode-llvm-coverage-toolchain.md")
PERMANENT_DIAGNOSTICS_TEXT = '''name: OpenCode Coverage Diagnostics CI

on:
  pull_request:
    paths:
      - '.github/workflows/opencode-review-dispatch.yml'
      - '.github/workflows/opencode-coverage-diagnostics-ci.yml'
      - 'requirements-opencode-review-ci*.txt'
      - 'scripts/ci/coverage_failure_summary.py'
      - 'scripts/ci/materialize_base_javascript_packages.py'
      - 'scripts/ci/materialize_base_python_requirements.py'
      - 'scripts/ci/sanitize_github_output_summary.py'
      - 'tests/test_coverage_materializer_failure_diagnostics.py'
      - 'tests/test_materialize_base_javascript_packages.py'
      - 'tests/test_materialize_base_python_requirements.py'
      - 'tests/test_opencode_libclang_toolchain_contract.py'
      - 'tests/test_opencode_agent_contract.py'
      - 'tests/test_sanitize_github_output_summary.py'

permissions:
  contents: read

concurrency:
  group: opencode-coverage-diagnostics-${{ github.event.pull_request.head.sha }}
  cancel-in-progress: true

env:
  FORCE_JAVASCRIPT_ACTIONS_TO_NODE24: true

jobs:
  python310:
    name: Python 3.10 source compatibility
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - name: Harden runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2.20.0
        with:
          egress-policy: audit

      - name: Checkout contributor head without persisted credentials
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          persist-credentials: false

      - name: Set up minimum supported Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.10'

      - name: Compile changed Python source under 3.10
        run: |
          python -m compileall -q \
            scripts/ci/coverage_failure_summary.py \
            scripts/ci/materialize_base_javascript_packages.py \
            scripts/ci/materialize_base_python_requirements.py \
            scripts/ci/sanitize_github_output_summary.py \
            tests/test_coverage_materializer_failure_diagnostics.py \
            tests/test_materialize_base_javascript_packages.py \
            tests/test_materialize_base_python_requirements.py \
            tests/test_opencode_libclang_toolchain_contract.py \
            tests/test_sanitize_github_output_summary.py

  quality:
    name: Diagnostics sanitization and coverage
    runs-on: ubuntu-24.04
    timeout-minutes: 15
    steps:
      - name: Harden runner
        uses: step-security/harden-runner@bf7454d06d71f1098171f2acdf0cd4708d7b5920 # v2.20.0
        with:
          egress-policy: audit

      - name: Checkout contributor head without persisted credentials
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0 # v7.0.0
        with:
          ref: ${{ github.event.pull_request.head.sha }}
          persist-credentials: false

      - name: Set up current stable Python
        uses: actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0
        with:
          python-version: '3.14'
          cache: pip
          cache-dependency-path: requirements-opencode-review-ci-hashes.txt

      - name: Install exact reviewed test toolchain
        run: >-
          python -m pip install --disable-pip-version-check --require-hashes
          -r requirements-opencode-review-ci-hashes.txt

      - name: Run materializer and sanitizer regressions at 100% coverage
        run: |
          python -m pytest \
            tests/test_materialize_base_javascript_packages.py \
            tests/test_materialize_base_python_requirements.py \
            tests/test_coverage_materializer_failure_diagnostics.py \
            tests/test_opencode_libclang_toolchain_contract.py \
            tests/test_sanitize_github_output_summary.py \
            --cov=scripts.ci.coverage_failure_summary \
            --cov=scripts.ci.materialize_base_javascript_packages \
            --cov=scripts.ci.materialize_base_python_requirements \
            --cov=scripts.ci.sanitize_github_output_summary \
            --cov-branch \
            --cov-fail-under=100 \
            -q

      - name: Enforce production docstrings
        run: >-
          python -m interrogate --fail-under 100
          scripts/ci/coverage_failure_summary.py
          scripts/ci/materialize_base_javascript_packages.py
          scripts/ci/materialize_base_python_requirements.py
          scripts/ci/sanitize_github_output_summary.py

      - name: Compile all changed source and tests
        run: |
          python -m compileall -q \
            scripts/ci/coverage_failure_summary.py \
            scripts/ci/materialize_base_javascript_packages.py \
            scripts/ci/materialize_base_python_requirements.py \
            scripts/ci/sanitize_github_output_summary.py \
            tests/test_coverage_materializer_failure_diagnostics.py \
            tests/test_materialize_base_javascript_packages.py \
            tests/test_materialize_base_python_requirements.py \
            tests/test_opencode_libclang_toolchain_contract.py \
            tests/test_sanitize_github_output_summary.py
'''


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    """Replace one exact reviewed anchor, failing closed on source drift."""
    if new in text:
        return text
    if text.count(old) != 1:
        raise SystemExit(f"expected one {label} anchor")
    return text.replace(old, new, 1)


def _restore_permanent_diagnostics() -> None:
    """Restore the permanent diagnostics workflow from reviewed source text."""
    DIAGNOSTICS_PATH.write_text(PERMANENT_DIAGNOSTICS_TEXT, encoding="utf-8")


def _update_dispatch_workflow() -> None:
    """Install matching libclang, export its path, and probe the shared library."""
    dispatch = DISPATCH_PATH.read_text(encoding="utf-8")
    slash = chr(92)
    package_old = f"              llvm-19 {slash}\n"
    package_new = f"              libclang-19-dev {slash}\n{package_old}"
    dispatch = _replace_once(dispatch, package_old, package_new, "llvm-19 package")
    env_old = "          ENV LLVM_COV=/usr/bin/llvm-cov-19\n"
    env_new = "          ENV LIBCLANG_PATH=/usr/lib/llvm-19/lib\n" + env_old
    dispatch = _replace_once(dispatch, env_old, env_new, "LLVM_COV environment")
    probe_old = '          RUN test -x "$LLVM_COV" && test -x "$LLVM_PROFDATA"\n'
    probe_new = (
        '          RUN test -d "$LIBCLANG_PATH" \\\n'
        '            && find "$LIBCLANG_PATH" -maxdepth 1 '
        "\\( -type f -o -type l \\) -name 'libclang.so*' "
        '-print -quit | grep -q . \\\n'
        '            && test -x "$LLVM_COV" \\\n'
        '            && test -x "$LLVM_PROFDATA"\n'
    )
    dispatch = _replace_once(dispatch, probe_old, probe_new, "LLVM executable probe")
    DISPATCH_PATH.write_text(dispatch, encoding="utf-8")


def _write_permanent_test() -> None:
    """Write the permanent toolchain and diagnostics-workflow contract."""
    TEST_PATH.write_text(
        '''"""Contracts for the central Rust bindgen and libclang coverage toolchain."""

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
''',
        encoding="utf-8",
    )


def _update_records() -> None:
    """Record the product fix and its APA 7 evidence without duplication."""
    changelog = CHANGELOG_PATH.read_text(encoding="utf-8")
    bullet = (
        "- Install version-aligned `libclang-19-dev`, export `LIBCLANG_PATH`, "
        "and fail the central coverage image build unless `libclang.so*` is "
        "present before bindgen-backed Rust coverage.\n"
    )
    if bullet not in changelog:
        anchor = "### Fixed\n\n"
        if changelog.count(anchor) != 1:
            raise SystemExit("changelog Fixed heading drifted")
        CHANGELOG_PATH.write_text(changelog.replace(anchor, anchor + bullet, 1), encoding="utf-8")

    doctoring = DOCTORING_PATH.read_text(encoding="utf-8")
    section = '''

## Bindgen and libclang compatibility boundary

`llvm-19` supplies the versioned coverage executables, while Rust crates using
`bindgen` also require the Clang C interface at build time. The central image
therefore installs matching `libclang-19-dev`, exports
`LIBCLANG_PATH=/usr/lib/llvm-19/lib`, and fails image construction unless a
regular file or symbolic link matching `libclang.so*` exists. Repository fuzz
and package-specific native validation remain independent required gates.

Debian Project. (2026). *libclang-19-dev: Clang library—Development package*.
Debian Packages. Retrieved August 5, 2026, from
https://packages.debian.org/trixie/libclang-19-dev

Ubuntu. (2026). *libclang-19-dev in noble-updates*. Ubuntu Packages. Retrieved
August 5, 2026, from https://packages.ubuntu.com/noble-updates/libclang-19-dev
'''
    if "## Bindgen and libclang compatibility boundary" not in doctoring:
        DOCTORING_PATH.write_text(doctoring.rstrip() + section + "\n", encoding="utf-8")


def main() -> None:
    """Apply every reviewed source transformation and preserve permanent CI."""
    _restore_permanent_diagnostics()
    _update_dispatch_workflow()
    _write_permanent_test()
    _update_records()


if __name__ == "__main__":
    main()
