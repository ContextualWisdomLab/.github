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
    assert '--pyproject "$project_dir/pyproject.toml"' in workflow
    assert "changed_files_for_coverage" in workflow
    assert "python_native_pytest_log" in workflow
    assert "python_native_changed_files" in workflow
    assert "if run_python_native_extension_classifier" in workflow


def test_python_failure_log_is_materialized_under_runner_temp() -> None:
    """Potentially large untrusted pytest output must use runner-owned storage."""

    function = _workflow_function("run_python_test_and_capture")
    assert (
        'python_native_pytest_log="$(mktemp '
        '"$RUNNER_TEMP/python-native-pytest.XXXXXX")"'
    ) in function


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
