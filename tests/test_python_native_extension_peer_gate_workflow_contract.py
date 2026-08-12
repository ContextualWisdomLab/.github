"""Permanent workflow contracts for the PyO3 source-only coverage boundary."""

from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).parents[1]
_REVIEW_WORKFLOW = _ROOT / ".github" / "workflows" / "opencode-review-dispatch.yml"
_QUALITY_WORKFLOW = (
    _ROOT
    / ".github"
    / "workflows"
    / "python-native-extension-peer-gate-quality-ci.yml"
)
_HELPER = "scripts/ci/python_native_extension_peer_gate.py"


def _review_workflow() -> str:
    """Return the protected OpenCode review workflow text."""

    return _REVIEW_WORKFLOW.read_text(encoding="utf-8")


def _quality_workflow() -> str:
    """Return the permanent PyO3 peer-gate quality workflow text."""

    return _QUALITY_WORKFLOW.read_text(encoding="utf-8")


def test_failed_python_suite_uses_bounded_repo_root_aware_classifier() -> None:
    """Only a real Python failure may enter the exact PyO3 classifier."""

    workflow = _review_workflow()
    assert "python_native_peer_check_required=0" in workflow
    assert "classify-pytest" in workflow
    assert _HELPER in workflow
    assert '--repo-root "$COVERAGE_SOURCE_WORKDIR"' in workflow
    assert '--pyproject "$project_dir/pyproject.toml"' in workflow
    assert "changed_files_for_coverage" in workflow
    assert "python_native_pytest_log" in workflow
    assert "python_native_changed_files" in workflow
    assert "if run_python_native_extension_classifier" in workflow


def test_source_only_native_failure_is_distinct_deferred_evidence() -> None:
    """A classifier result is never serialized as ordinary passing coverage."""

    workflow = _review_workflow()
    assert "### Python native-extension source-only deferral" in workflow
    assert '- Result: DEFERRED' in workflow
    assert (
        "the unchanged declared PyO3 module was unavailable in the source-only "
        "sandbox" in workflow
    )
    assert "exact-head Python, Rust/PyO3, and package CheckRuns" in workflow
    assert (
        "Python native-extension peer evidence: deferred source-only collection "
        "requires successful exact-head peer checks" in workflow
    )


def test_approval_requires_live_exact_head_python_rust_and_package_checkruns() -> None:
    """The trusted approval phase must validate all three exact-head peer checks."""

    workflow = _review_workflow()
    assert "python_native_peer_check_required" in workflow
    assert "require-checks" in workflow
    assert '--head-sha "$PR_HEAD_SHA"' in workflow
    for requirement in ("CI::python", "CI::rust", "CI::package"):
        assert f'--required-check "{requirement}"' in workflow
    assert "check-runs" in workflow
    assert "__typename" in workflow
    assert "CheckRun" in workflow
    assert "r_peer_check_required" in workflow
    assert (
        "require_r_cmd_check_for_deferred_coverage" in workflow
        or "R CMD check" in workflow
    )


def test_quality_workflow_covers_supported_pythons_and_all_contract_files() -> None:
    """Python 3.10/3.14, coverage, docstrings, and integration stay permanent."""

    workflow = _quality_workflow()
    for path in (
        _HELPER,
        "tests/test_python_native_extension_peer_gate.py",
        "tests/test_python_native_extension_peer_gate_nested_project.py",
        "tests/test_python_native_extension_peer_gate_workflow_contract.py",
        ".github/workflows/opencode-review-dispatch.yml",
        ".github/workflows/python-native-extension-peer-gate-quality-ci.yml",
        "docs/doctoring/python-native-extension-peer-evidence.md",
        "CHANGELOG.md",
    ):
        assert path in workflow
    assert 'python-version: "3.10"' in workflow
    assert 'python-version: "3.14"' in workflow
    assert "--cov-branch" in workflow or "branch = True" in workflow
    assert "fail_under = 100" in workflow
    assert "interrogate --fail-under 100" in workflow
    assert "compileall -q" in workflow
    assert "actionlint" in workflow
    assert '"${RUNNER_TEMP}/actionlint" -shellcheck=' in workflow
