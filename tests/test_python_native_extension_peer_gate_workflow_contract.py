"""Permanent workflow contracts for the PyO3 source-only coverage boundary."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import textwrap


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


def _workflow_function(name: str) -> str:
    """Return one shell function from the embedded review script."""

    workflow = _review_workflow()
    marker = f"          {name}() {{"
    start = workflow.index(marker)
    end = workflow.index("\n          }\n\n", start) + len("\n          }")
    return textwrap.dedent(workflow[start:end])


def test_failed_python_suite_uses_bounded_repo_root_aware_classifier() -> None:
    """Only a real Python failure may enter the exact PyO3 classifier."""

    workflow = _review_workflow()
    assert "python_native_peer_check_required=0" in workflow
    assert "classify-pytest" in workflow
    assert _HELPER in workflow
    assert '--repo-root "$COVERAGE_SOURCE_WORKDIR"' in workflow
    assert '--logical-pyproject "$project_dir/pyproject.toml"' in workflow
    assert "changed_files_for_coverage" in workflow
    assert "python_native_pytest_log" in workflow
    assert "python_native_changed_files" in workflow
    assert "if run_python_native_extension_classifier" in workflow


def test_workflow_classifier_executes_sealed_snapshot_with_logical_path(
    tmp_path: Path,
) -> None:
    """The real workflow command must separate trusted bytes from repo location."""

    repository = tmp_path / "repository"
    repository.mkdir()
    pyproject_text = """\
[build-system]
build-backend = "maturin"

[tool.maturin]
bindings = "pyo3"
manifest-path = "crates/native/Cargo.toml"
module-name = "native_demo._core"
python-source = "python"
"""
    (repository / "pyproject.toml").write_text(pyproject_text, encoding="utf-8")
    pytest_log = tmp_path / "pytest.log"
    pytest_log.write_text(
        """\
____________ ERROR collecting tests/test_api.py ____________
tests/test_api.py:3: in <module>
    import native_demo._core
E   ModuleNotFoundError: No module named 'native_demo._core'
!!!!!!!! Interrupted: 1 error during collection !!!!!!!!
""",
        encoding="utf-8",
    )
    changed_files = tmp_path / "changed-files.txt"
    changed_files.write_text("python/native_demo/api.py\n", encoding="utf-8")
    sealed_snapshot = tmp_path / "sealed-metadata"
    sealed_snapshot.write_text(pyproject_text, encoding="utf-8")

    script = "\n".join(
        (
            "set -euo pipefail",
            _workflow_function("run_python_native_extension_classifier"),
            (
                "run_python_native_extension_classifier . "
                f"{pytest_log!s} {changed_files!s} {sealed_snapshot!s}"
            ),
        )
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=repository,
        env={
            **os.environ,
            "GITHUB_WORKSPACE": str(_ROOT),
            "COVERAGE_SOURCE_WORKDIR": str(repository),
        },
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr
    assert "unchanged declared native module native_demo._core" in result.stdout


def test_python_coverage_executes_classifier_path_and_publishes_peer_requirement() -> None:
    """Every pytest path must classify failures and serialize the peer gate."""

    coverage_function = _workflow_function("run_python_test_coverage")
    workflow = _review_workflow()
    evidence_start = workflow.index("          if has_changed_tracked_files '*.py';")
    evidence_end = workflow.index(
        '          javascript_package_dirs="$(javascript_coverage_package_dirs)"',
        evidence_start,
    )
    python_evidence = workflow[evidence_start:evidence_end]
    approval_function = _workflow_function("publish_blockers_after_model_unavailable")

    assert coverage_function.count("run_python_test_and_capture") == 3
    assert "python_native_peer_check_required" in python_evidence
    assert (
        "Python native-extension peer evidence: deferred source-only collection "
        "requires successful exact-head peer checks" in python_evidence
    )
    assert "require_python_native_peer_checks_for_deferred_coverage" in (
        approval_function
    )
    assert workflow.count("require_python_native_peer_checks_for_deferred_coverage") == 3


def test_python_failure_log_is_materialized_under_runner_temp() -> None:
    """Potentially large untrusted pytest output must use runner-owned storage."""

    function = _workflow_function("run_python_test_and_capture")
    assert (
        'python_native_pytest_log="$(mktemp '
        '"$RUNNER_TEMP/python-native-pytest.XXXXXX")"'
    ) in function


def test_python_metadata_snapshot_comes_from_exact_head_git_object() -> None:
    """Later tests cannot rewrite metadata or block projects without pyproject."""

    function = _workflow_function("run_python_test_and_capture")
    assert 'pyproject_repository_path="pyproject.toml"' in function
    assert (
        'pyproject_repository_path="${project_dir#./}/pyproject.toml"' in function
    )
    assert (
        '"${PR_HEAD_SHA:-HEAD}:${pyproject_repository_path}"'
        in function
    )
    assert 'if trusted_git show \\' in function
    assert 'chmod 0444 "$python_native_pyproject_snapshot"' in function
    assert ': >"$python_native_pyproject_snapshot"' in function
    snapshot_start = function.index("if trusted_git show")
    snapshot_end = function.index('\n\n  append "### ${label}"', snapshot_start)
    assert "failures" not in function[snapshot_start:snapshot_end]
    assert 'if [ -f "$project_dir/pyproject.toml" ]' not in function


def test_renamed_native_input_preserves_old_and_new_paths(tmp_path: Path) -> None:
    """A rename out of a native boundary must still expose the old path."""

    repository = tmp_path / "repository"
    repository.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.invalid"],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"], cwd=repository, check=True
    )
    native_input = repository / "crates" / "native_bridge" / "Cargo.toml"
    native_input.parent.mkdir(parents=True)
    native_input.write_text("[package]\nname = 'native-bridge'\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repository, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repository, check=True)
    base_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()
    destination = repository / "docs" / "retired-native-manifest.toml"
    destination.parent.mkdir()
    subprocess.run(
        [
            "git",
            "mv",
            str(native_input.relative_to(repository)),
            str(destination.relative_to(repository)),
        ],
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-qm", "move manifest"], cwd=repository, check=True
    )
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repository, text=True
    ).strip()

    script = "\n".join(
        (
            "set -euo pipefail",
            "trusted_git() { git \"$@\"; }",
            _workflow_function("changed_files_for_coverage"),
            "changed_files_for_coverage",
        )
    )
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=repository,
        env={**os.environ, "PR_BASE_SHA": base_sha, "PR_HEAD_SHA": head_sha},
        text=True,
        capture_output=True,
        check=True,
    )
    assert result.stdout.splitlines() == [
        "crates/native_bridge/Cargo.toml",
        "docs/retired-native-manifest.toml",
    ]


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


def test_compact_coverage_decision_preserves_native_peer_requirement() -> None:
    """The published compact summary must carry the fail-closed peer marker."""

    workflow = _review_workflow()
    decision_start = workflow.index('          append "## Coverage Decision"')
    decision_end = workflow.index(
        '          coverage_output_file="$(mktemp)"', decision_start
    )
    compact_decision_source = workflow[decision_start:decision_end]

    assert 'if [ "$python_native_peer_check_required" -eq 1 ]; then' in (
        compact_decision_source
    )
    assert (
        "Python native-extension peer evidence: deferred source-only collection "
        "requires successful exact-head peer checks" in compact_decision_source
    )


def test_approval_requires_live_exact_head_python_rust_and_package_checkruns() -> None:
    """The trusted approval phase must validate all three exact-head peer checks."""

    workflow = _review_workflow()
    function = _workflow_function(
        "collect_successful_python_native_peer_check_evidence"
    )
    assert "python_native_peer_check_required" in workflow
    assert "require-checks" in function
    assert '--head-sha "$PR_HEAD_SHA"' in function
    for requirement in ("CI::python", "CI::rust", "CI::package"):
        assert f'--required-check "{requirement}"' in function
    assert "check-runs" in function
    assert "__typename" in function
    assert "CheckRun" in function
    assert "r_peer_check_required" in workflow
    assert (
        "require_r_cmd_check_for_deferred_coverage" in workflow
        or "R CMD check" in workflow
    )


def test_exact_head_peer_check_lookup_paginates_all_checkruns(tmp_path: Path) -> None:
    """Required checks beyond GraphQL's first 100 contexts remain authoritative."""

    head_sha = "a" * 40
    first_page = {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": head_sha,
                    "statusCheckRollup": {
                        "contexts": {
                            "nodes": [
                                {
                                    "__typename": "CheckRun",
                                    "name": f"irrelevant-{index}",
                                    "status": "COMPLETED",
                                    "conclusion": "SUCCESS",
                                    "checkSuite": {
                                        "workflowRun": {"workflow": {"name": "Other"}}
                                    },
                                }
                                for index in range(100)
                            ],
                            "pageInfo": {
                                "hasNextPage": True,
                                "endCursor": "cursor-100",
                            },
                        }
                    },
                }
            }
        }
    }
    second_page = {
        "data": {
            "repository": {
                "pullRequest": {
                    "headRefOid": head_sha,
                    "statusCheckRollup": {
                        "contexts": {
                            "nodes": [
                                {
                                    "__typename": "CheckRun",
                                    "name": name,
                                    "status": "COMPLETED",
                                    "conclusion": "SUCCESS",
                                    "checkSuite": {
                                        "workflowRun": {"workflow": {"name": "CI"}}
                                    },
                                }
                                for name in ("python", "rust", "package")
                            ],
                            "pageInfo": {
                                "hasNextPage": False,
                                "endCursor": None,
                            },
                        }
                    },
                }
            }
        }
    }
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "query = next((arg.split('=', 1)[1] for arg in sys.argv "
        "if arg.startswith('query=')), '')\n"
        "if ('after: $cursor' not in query or 'pageInfo' not in query "
        "or query.count('{') != query.count('}')):\n"
        "    raise SystemExit(2)\n"
        "cursor = next((arg.split('=', 1)[1] for arg in sys.argv "
        "if arg.startswith('cursor=')), '')\n"
        "payload = json.loads(os.environ['SECOND_PAGE'] if cursor == 'cursor-100' "
        "else os.environ['FIRST_PAGE'])\n"
        "json.dump(payload, sys.stdout)\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    output_file = tmp_path / "checks.json"
    shell = "\n".join(
        (
            "set -euo pipefail",
            "check_lookup_api_timeout_seconds() { printf '5\\n'; }",
            _workflow_function(
                "collect_successful_python_native_peer_check_evidence"
            ),
            f"collect_successful_python_native_peer_check_evidence {output_file!s}",
        )
    )
    result = subprocess.run(
        ["bash", "-c", shell],
        cwd=_ROOT,
        env={
            **os.environ,
            "FIRST_PAGE": json.dumps(first_page),
            "SECOND_PAGE": json.dumps(second_page),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "GH_REPOSITORY": "ContextualWisdomLab/.github",
            "PR_NUMBER": "789",
            "PR_HEAD_SHA": head_sha,
            "GITHUB_WORKSPACE": str(_ROOT),
        },
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr


def test_quality_workflow_covers_supported_pythons_and_all_contract_files() -> None:
    """Python 3.10/3.14, coverage, docstrings, and integration stay permanent."""

    workflow = _quality_workflow()
    for path in (
        _HELPER,
        "tests/test_python_native_extension_peer_gate.py",
        "tests/test_python_native_extension_peer_gate_file_safety.py",
        "tests/test_python_native_extension_peer_gate_nested_project.py",
        "tests/test_python_native_extension_peer_gate_requirements_directory.py",
        "tests/test_python_native_extension_peer_gate_workflow_contract.py",
        ".github/workflows/opencode-review-dispatch.yml",
        ".github/workflows/python-native-extension-peer-gate-quality-ci.yml",
        "docs/doctoring/python-native-extension-peer-evidence.md",
        "docs/doctoring/python-native-extension-peer-file-safety.md",
        "AGENTS.md",
        "ARCHITECTURE.md",
        "CHANGELOG.md",
    ):
        assert path in workflow
    trigger_contract = workflow.split("\nconcurrency:", 1)[0]
    for policy_path in ("AGENTS.md", "ARCHITECTURE.md"):
        assert trigger_contract.count(f'- "{policy_path}"') == 2
    assert 'python-version: "3.10"' in workflow
    assert 'python-version: "3.14"' in workflow
    assert "--cov-branch" in workflow or "branch = True" in workflow
    assert "fail_under = 100" in workflow
    assert "interrogate --fail-under 100" in workflow
    assert "compileall -q" in workflow
    assert "actionlint" in workflow
    assert '"${RUNNER_TEMP}/actionlint" -shellcheck=' in workflow


def test_unreleased_changelog_has_unique_sibling_headings() -> None:
    """Keep a Changelog sections must not duplicate sibling headings."""

    unreleased = (
        (_ROOT / "CHANGELOG.md")
        .read_text(encoding="utf-8")
        .split("## [Unreleased]", 1)[1]
        .split("\n## ", 1)[0]
    )
    headings = [
        line
        for line in unreleased.splitlines()
        if line.startswith("### ")
    ]
    assert len(headings) == len(set(headings))
