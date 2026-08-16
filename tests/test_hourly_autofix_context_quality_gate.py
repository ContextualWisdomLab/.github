"""Contract tests for exact-head quality evidence of autofix context production."""

import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys

import pytest

from scripts.ci import pr_review_autofix_context as context


WORKFLOW = Path(".github/workflows/hourly-nvidia-nim-review-repair.yml")


def test_context_helper_is_part_of_the_focused_exact_head_quality_gate() -> None:
    """Require trigger, full-suite, coverage, docstring, and compile evidence."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("- scripts/ci/pr_review_autofix_context.py") == 2
    assert workflow.count("- tests/test_pr_review_fix_scheduler.py") == 2
    assert workflow.count("- tests/test_hourly_autofix_context_quality_gate.py") == 2
    assert (
        workflow.count("- tests/test_pr_review_autofix_writer_security_contract.py")
        == 2
    )
    pytest_start = workflow.index("python -m pytest -q")
    coverage_start = workflow.index(
        "--cov=scripts.ci.pr_review_conflict_scope", pytest_start
    )
    pytest_targets = workflow[pytest_start:coverage_start]
    assert "tests/" not in pytest_targets
    assert (
        "python -m pytest -q \\\n"
        "            --cov=scripts.ci.pr_review_conflict_scope \\\n"
        "            --cov=scripts.ci.pr_review_autofix_context"
    ) in workflow
    assert "--cov=scripts.ci.pr_review_autofix_context \\" in workflow
    assert (
        "scripts/ci/pr_review_conflict_scope.py \\\n"
        "            scripts/ci/pr_review_autofix_context.py"
    ) in workflow
    assert (
        "scripts/ci/pr_review_conflict_scope.py \\\n"
        "            scripts/ci/pr_review_autofix_context.py \\\n"
        "            tests/test_pr_review_conflict_scope.py"
    ) in workflow


def test_context_helper_covers_unknown_checks_and_explicit_path_output(
    monkeypatch, tmp_path: Path
) -> None:
    """Exercise fail-closed status filtering and the explicit sealed-output CLI path."""
    head = "a" * 40
    pull_request = {
        "number": 7,
        "title": "Bound context authority",
        "url": "https://example.invalid/pull/7",
        "headRefName": "feature",
        "baseRefName": "main",
        "headRefOid": head,
        "baseRefOid": "b" * 40,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [{"__typename": "UnknownStatusNode"}],
    }
    monkeypatch.setattr(context, "pr_view", lambda _repo, _number: pull_request)
    monkeypatch.setattr(
        context,
        "current_reviews",
        lambda _repo, _number, _head_sha: [],
    )
    monkeypatch.setattr(context, "review_threads", lambda _repo, _number: [])

    assert context.check_summary(pull_request["statusCheckRollup"]) == []

    markdown_output = tmp_path / "context.md"
    allowed_paths_output = tmp_path / "explicit-allowed-paths.zlist"
    assert (
        context.main(
            [
                "--repo",
                "owner/repo",
                "--pr-number",
                "7",
                "--head-sha",
                head,
                "--output",
                str(markdown_output),
                "--allowed-paths-output",
                str(allowed_paths_output),
            ]
        )
        == 0
    )
    assert allowed_paths_output.read_bytes() == b""
    assert Path(f"{allowed_paths_output}.sha256").read_text(encoding="ascii") == (
        f"{hashlib.sha256(b'').hexdigest()}\n"
    )
    assert markdown_output.is_file()


def test_context_rejects_leading_and_trailing_space_paths() -> None:
    """Git paths with external spaces must not normalize into another file."""
    threads = [
        {
            "comments": {
                "nodes": [
                    {"path": " src/reviewed.py"},
                    {"path": "src/reviewed.py "},
                ]
            }
        }
    ]

    assert context.thread_paths(threads) == []


def test_context_rejects_review_authenticated_control_plane_paths() -> None:
    """Untrusted review threads must never authorize autonomous writer controls."""
    threads = [
        {
            "comments": {
                "nodes": [
                    {"path": ".github/workflows/pr-review-autofix.yml"},
                    {"path": ".github/actions/trusted/action.yml"},
                    {"path": ".github/CODEOWNERS"},
                    {"path": "scripts/ci/pr_review_autofix_context.py"},
                    {"path": "scripts/ci/pr_review_conflict_scope.py"},
                    {"path": "src/reviewed.py"},
                ]
            }
        }
    ]

    assert context.thread_paths(threads) == ["src/reviewed.py"]


def test_context_script_main_guard_completes_on_valid_cli_input(
    monkeypatch, tmp_path: Path
) -> None:
    """Exercise the executable module guard through a successful bounded CLI run."""
    head = "a" * 40
    output = tmp_path / "script-context.md"
    pull_request = {
        "number": 7,
        "title": "CLI context",
        "url": "https://example.invalid/pull/7",
        "headRefName": "feature",
        "baseRefName": "main",
        "headRefOid": head,
        "baseRefOid": "b" * 40,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [],
    }

    def fake_run(argv, **_kwargs):
        joined = " ".join(argv)
        if argv[1:3] == ["pr", "view"]:
            payload = pull_request
        elif "pulls/7/reviews" in joined:
            payload = [[]]
        elif argv[1:3] == ["api", "graphql"]:
            payload = {
                "data": {
                    "repository": {
                        "pullRequest": {"reviewThreads": {"nodes": []}}
                    }
                }
            }
        else:
            raise AssertionError(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(payload),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "pr_review_autofix_context.py",
            "--repo",
            "owner/repo",
            "--pr-number",
            "7",
            "--head-sha",
            head,
            "--output",
            str(output),
        ],
    )

    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(
            "scripts/ci/pr_review_autofix_context.py",
            run_name="__main__",
        )

    assert exit_info.value.code == 0
    assert output.is_file()
