"""Tests for pr_review_autofix_context."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts.ci.pr_review_autofix_context import (
    check_summary,
    parse_args,
    repo_parts,
    thread_paths,
)


def test_repo_parts_valid() -> None:
    """Test repo_parts with valid input."""
    assert repo_parts("owner/name") == ("owner", "name")


def test_repo_parts_invalid_missing_slash() -> None:
    """Test repo_parts with invalid input (missing slash)."""
    with pytest.raises(ValueError, match="repo must be OWNER/NAME"):
        repo_parts("ownername")


def test_repo_parts_invalid_empty_owner() -> None:
    """Test repo_parts with invalid input (empty owner)."""
    with pytest.raises(ValueError, match="repo must be OWNER/NAME"):
        repo_parts("/name")


def test_repo_parts_invalid_empty_name() -> None:
    """Test repo_parts with invalid input (empty name)."""
    with pytest.raises(ValueError, match="repo must be OWNER/NAME"):
        repo_parts("owner/")


def test_check_summary_empty() -> None:
    """Test check_summary with empty or None input."""
    assert check_summary(None) == []
    assert check_summary([]) == []


def test_check_summary_check_run() -> None:
    """Test check_summary with CheckRun nodes."""
    status_rollup = [
        {
            "__typename": "CheckRun",
            "name": "lint",
            "workflowName": "CI",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
        },
        {
            "__typename": "CheckRun",
            "name": "test",
            "status": "IN_PROGRESS",
            "conclusion": "",
        },
    ]
    assert check_summary(status_rollup) == [
        "- CI/lint: COMPLETED SUCCESS",
        "- test: IN_PROGRESS",
    ]


def test_check_summary_status_context() -> None:
    """Test check_summary with StatusContext nodes."""
    status_rollup = [
        {
            "__typename": "StatusContext",
            "context": "continuous-integration/travis-ci/pr",
            "state": "SUCCESS",
        },
    ]
    assert check_summary(status_rollup) == [
        "- continuous-integration/travis-ci/pr: SUCCESS",
    ]


def test_check_summary_mixed() -> None:
    """Test check_summary with mixed node types."""
    status_rollup = [
        {
            "__typename": "CheckRun",
            "name": "lint",
            "workflowName": "CI",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
        },
        {
            "__typename": "StatusContext",
            "context": "continuous-integration/travis-ci/pr",
            "state": "SUCCESS",
        },
        {
            "__typename": "UnknownType",
        },
    ]
    assert check_summary(status_rollup) == [
        "- CI/lint: COMPLETED SUCCESS",
        "- continuous-integration/travis-ci/pr: SUCCESS",
    ]


def test_thread_paths_empty() -> None:
    """Test thread_paths with empty input."""
    assert thread_paths([]) == []


def test_thread_paths_valid() -> None:
    """Test thread_paths extracts unique paths."""
    threads = [
        {"comments": {"nodes": [{"path": "file1.txt"}]}},
        {"comments": {"nodes": [{"path": "file2.txt"}, {"path": "file1.txt"}]}},
    ]
    assert thread_paths(threads) == ["file1.txt", "file2.txt"]


def test_thread_paths_ignore_invalid() -> None:
    """Test thread_paths ignores absolute and relative up paths."""
    threads = [
        {"comments": {"nodes": [{"path": "/etc/passwd"}]}},
        {"comments": {"nodes": [{"path": "../secrets.txt"}]}},
        {"comments": {"nodes": [{"path": "a/../../secrets.txt"}]}},
        {"comments": {"nodes": [{"path": "  "}]}},
        {"comments": {"nodes": [{}]}},
        {"comments": {}},
        {},
    ]
    assert thread_paths(threads) == []


def test_parse_args_valid() -> None:
    """Test parse_args with valid arguments."""
    args = parse_args(
        [
            "--repo",
            "owner/name",
            "--pr-number",
            "123",
            "--head-sha",
            "0123456789abcdef0123456789abcdef01234567",
            "--output",
            "out.txt",
        ]
    )
    assert args.repo == "owner/name"
    assert args.pr_number == 123
    assert args.head_sha == "0123456789abcdef0123456789abcdef01234567"
    assert args.output == Path("out.txt")


def test_parse_args_missing_repo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test parse_args raises error when repo is missing."""
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--pr-number",
                "123",
                "--head-sha",
                "0123456789abcdef0123456789abcdef01234567",
                "--output",
                "out.txt",
            ]
        )


def test_parse_args_invalid_repo() -> None:
    """Test parse_args raises error for invalid repo format."""
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--repo",
                "invalid_repo",
                "--pr-number",
                "123",
                "--head-sha",
                "0123456789abcdef0123456789abcdef01234567",
                "--output",
                "out.txt",
            ]
        )


def test_parse_args_invalid_pr_number() -> None:
    """Test parse_args raises error for invalid PR number."""
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--repo",
                "owner/name",
                "--pr-number",
                "0",
                "--head-sha",
                "0123456789abcdef0123456789abcdef01234567",
                "--output",
                "out.txt",
            ]
        )


def test_parse_args_invalid_sha() -> None:
    """Test parse_args raises error for invalid head SHA."""
    with pytest.raises(SystemExit):
        parse_args(
            [
                "--repo",
                "owner/name",
                "--pr-number",
                "123",
                "--head-sha",
                "short",
                "--output",
                "out.txt",
            ]
        )

def test_main(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test main function."""
    from scripts.ci.pr_review_autofix_context import main

    # Mock write_context to just check arguments and avoid actual external calls
    def mock_write_context(repo: str, number: int, head_sha: str, output: Path) -> None:
        """Mock write_context function."""
        assert repo == "owner/name"
        assert number == 123
        assert head_sha == "0123456789abcdef0123456789abcdef01234567"
        assert output == tmp_path / "out.txt"

    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.write_context", mock_write_context)

    argv = [
        "--repo",
        "owner/name",
        "--pr-number",
        "123",
        "--head-sha",
        "0123456789abcdef0123456789abcdef01234567",
        "--output",
        str(tmp_path / "out.txt"),
    ]
    assert main(argv) == 0


import json
import subprocess

def test_run_json_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_json on success."""
    from scripts.ci.pr_review_autofix_context import run_json

    class MockCompletedProcess:
        """Mock CompletedProcess."""
        returncode = 0
        stdout = '{"key": "value"}'
        stderr = ""

    def mock_run(*args: object, **kwargs: object) -> MockCompletedProcess:
        """Mock run function."""
        return MockCompletedProcess()

    monkeypatch.setattr(subprocess, "run", mock_run)
    assert run_json(["some", "args"]) == {"key": "value"}


def test_run_json_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test run_json on failure."""
    from scripts.ci.pr_review_autofix_context import run_json

    class MockCompletedProcess:
        """Mock CompletedProcess."""
        returncode = 1
        stdout = ""
        stderr = "error message"

    def mock_run(*args: object, **kwargs: object) -> MockCompletedProcess:
        """Mock run function."""
        return MockCompletedProcess()

    monkeypatch.setattr(subprocess, "run", mock_run)
    with pytest.raises(RuntimeError, match="error message"):
        run_json(["some", "args"])


def test_pr_view(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test pr_view."""
    from scripts.ci.pr_review_autofix_context import pr_view

    def mock_run_json(args: list[str]) -> dict[str, str]:
        """Mock run_json function."""
        assert args == [
            "pr",
            "view",
            "123",
            "--repo",
            "owner/name",
            "--json",
            "number,title,body,headRefName,baseRefName,headRefOid,baseRefOid,mergeStateStatus,statusCheckRollup,url",
        ]
        return {"title": "PR Title"}

    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.run_json", mock_run_json)
    assert pr_view("owner/name", 123) == {"title": "PR Title"}


def test_current_reviews_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test current_reviews."""
    from scripts.ci.pr_review_autofix_context import current_reviews

    head_sha = "a" * 40

    def mock_run_json(args: list[str]) -> list[list[dict[str, str]]]:
        """Mock run_json function."""
        return [
            [
                {"commit_id": head_sha, "state": "APPROVED"},
                {"body": head_sha, "state": "CHANGES_REQUESTED"},
                {"commit_id": "b" * 40, "state": "APPROVED"},
                {"commit_id": head_sha, "state": "COMMENTED"},
            ]
        ]

    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.run_json", mock_run_json)
    reviews = current_reviews("owner/name", 123, head_sha)
    assert len(reviews) == 2
    assert reviews[0]["state"] == "APPROVED"
    assert reviews[1]["state"] == "CHANGES_REQUESTED"


def test_review_threads_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test review_threads."""
    from scripts.ci.pr_review_autofix_context import review_threads

    def mock_run_json(args: list[str]) -> dict[str, object]:
        """Mock run_json function."""
        return {
            "data": {
                "repository": {
                    "pullRequest": {
                        "reviewThreads": {
                            "nodes": [
                                {"isResolved": False, "isOutdated": False, "id": "1"},
                                {"isResolved": True, "isOutdated": False, "id": "2"},
                                {"isResolved": False, "isOutdated": True, "id": "3"},
                            ]
                        }
                    }
                }
            }
        }

    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.run_json", mock_run_json)
    threads = review_threads("owner/name", 123)
    assert len(threads) == 1
    assert threads[0]["id"] == "1"


def test_write_context_valid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test write_context successfully writes output."""
    from scripts.ci.pr_review_autofix_context import write_context

    head_sha = "a" * 40
    pr_data = {
        "url": "https://github.com",
        "title": "PR Title",
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": head_sha,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [],
    }

    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.pr_view", lambda r, n: pr_data)
    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.current_reviews", lambda r, n, h: [])
    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.review_threads", lambda r, n: [])

    out_file = tmp_path / "out.txt"
    write_context("owner/name", 123, head_sha, out_file)

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "PR Review Autofix Context" in content
    assert "PR Title" in content

def test_write_context_mismatch_sha(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test write_context raises RuntimeError on SHA mismatch."""
    from scripts.ci.pr_review_autofix_context import write_context

    head_sha = "a" * 40
    pr_data = {
        "headRefOid": "b" * 40,
    }

    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.pr_view", lambda r, n: pr_data)

    out_file = tmp_path / "out.txt"
    with pytest.raises(RuntimeError, match="live head b.* does not match expected a.*"):
        write_context("owner/name", 123, head_sha, out_file)


def test_write_context_with_content(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Test write_context successfully writes output with full content."""
    from scripts.ci.pr_review_autofix_context import write_context

    head_sha = "a" * 40
    pr_data = {
        "url": "https://github.com",
        "title": "PR Title",
        "baseRefName": "main",
        "baseRefOid": "b" * 40,
        "headRefName": "feature",
        "headRefOid": head_sha,
        "mergeStateStatus": "CLEAN",
        "statusCheckRollup": [{"__typename": "CheckRun", "name": "test"}],
    }

    reviews_data = [
        {"state": "APPROVED", "user": {"login": "user1"}, "body": "looks good"},
        {"state": "CHANGES_REQUESTED", "user": {}, "body": ""},
    ]

    threads_data = [
        {
            "id": "thread1",
            "comments": {
                "nodes": [
                    {
                        "author": {"login": "user2"},
                        "path": "file1.txt",
                        "line": 10,
                        "body": "fix this",
                    },
                    {
                        "author": {},
                        "originalLine": 20,
                        "body": "",
                    }
                ]
            }
        }
    ]

    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.pr_view", lambda r, n: pr_data)
    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.current_reviews", lambda r, n, h: reviews_data)
    monkeypatch.setattr("scripts.ci.pr_review_autofix_context.review_threads", lambda r, n: threads_data)

    out_file = tmp_path / "out.txt"
    write_context("owner/name", 123, head_sha, out_file)

    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "PR Title" in content
    assert "- `file1.txt`" in content
    assert "### APPROVED by user1" in content
    assert "looks good" in content
    assert "### CHANGES_REQUESTED by unknown" in content
    assert "(empty body)" in content
    assert "### Thread thread1" in content
    assert "- user2 at file1.txt:10" in content
    assert "fix this" in content
    assert "- unknown at (no path):20" in content
    assert "- test:" in content


def test_module_execution() -> None:
    """Test module execution block."""
    import runpy
    import sys
    from unittest.mock import patch

    with patch.object(sys, "argv", ["scripts/ci/pr_review_autofix_context.py", "--help"]):
        with pytest.raises(SystemExit) as excinfo:
            runpy.run_module("scripts.ci.pr_review_autofix_context", run_name="__main__")
        assert excinfo.value.code == 0
