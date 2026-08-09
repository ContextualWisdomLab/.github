"""Tests for the check_summary function in pr_review_autofix_context.py."""

from typing import Any

from scripts.ci.pr_review_autofix_context import check_summary


def test_check_summary_none_or_empty() -> None:
    """Test check_summary with None or an empty list."""
    assert check_summary(None) == []
    assert check_summary([]) == []


def test_check_summary_checkrun_full() -> None:
    """Test check_summary with a complete CheckRun node."""
    data: list[dict[str, Any]] = [{
        "__typename": "CheckRun",
        "name": "lint",
        "workflowName": "CI",
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
    }]
    assert check_summary(data) == ["- CI/lint: COMPLETED SUCCESS"]


def test_check_summary_checkrun_no_workflow() -> None:
    """Test check_summary when a CheckRun node lacks a workflow name."""
    data: list[dict[str, Any]] = [{
        "__typename": "CheckRun",
        "name": "lint",
        "status": "COMPLETED",
        "conclusion": "FAILURE",
    }]
    assert check_summary(data) == ["- lint: COMPLETED FAILURE"]


def test_check_summary_checkrun_no_name() -> None:
    """Test check_summary when a CheckRun node lacks a name."""
    data: list[dict[str, Any]] = [{
        "__typename": "CheckRun",
        "workflowName": "CI",
        "status": "IN_PROGRESS",
    }]
    # if name is missing, it falls back to "check"
    assert check_summary(data) == ["- CI/check: IN_PROGRESS"]


def test_check_summary_checkrun_no_name_no_workflow() -> None:
    """Test check_summary when a CheckRun node lacks both name and workflow."""
    data: list[dict[str, Any]] = [{
        "__typename": "CheckRun",
    }]
    assert check_summary(data) == ["- check:"]


def test_check_summary_status_context() -> None:
    """Test check_summary with a StatusContext node."""
    data: list[dict[str, Any]] = [{
        "__typename": "StatusContext",
        "context": "security",
        "state": "SUCCESS",
    }]
    assert check_summary(data) == ["- security: SUCCESS"]


def test_check_summary_unknown_typename() -> None:
    """Test check_summary handles nodes with unknown or missing typenames gracefully."""
    data: list[dict[str, Any]] = [{
        "__typename": "Unknown",
        "name": "lint",
    }, {
        "name": "missing_typename",
    }]
    assert check_summary(data) == []


def test_check_summary_multiple() -> None:
    """Test check_summary with multiple mixed nodes."""
    data: list[dict[str, Any]] = [
        {
            "__typename": "CheckRun",
            "name": "test",
            "workflowName": "Tests",
            "status": "COMPLETED",
            "conclusion": "FAILURE",
        },
        {
            "__typename": "StatusContext",
            "context": "code-quality",
            "state": "PENDING",
        },
        {
            "__typename": "Unknown",
        },
    ]
    assert check_summary(data) == [
        "- Tests/test: COMPLETED FAILURE",
        "- code-quality: PENDING",
    ]
