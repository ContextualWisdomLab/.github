"""Static contract for the central hourly PR review-fix scheduler."""

from __future__ import annotations

from pathlib import Path


_WORKFLOW = Path(".github/workflows/pr-review-fix-scheduler.yml")


def _workflow_text() -> str:
    """Return the canonical scheduler workflow text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_review_fix_scheduler_runs_once_each_hour() -> None:
    """The bounded repair dispatcher uses the requested hourly heartbeat."""
    text = _workflow_text()

    assert 'cron: "23 * * * *"' in text
    assert 'cron: "23 */2 * * *"' not in text


def test_scheduled_scheduler_uses_configured_or_caller_repository() -> None:
    """The central heartbeat stays reusable and never hard-codes one product."""
    text = _workflow_text()
    target_expression = (
        "github.event.client_payload.target_repository || "
        "inputs.target_repository || "
        "vars.PR_REVIEW_FIX_TARGET_REPOSITORY || "
        "github.repository"
    )

    assert text.count(target_expression) == 2
    assert "ContextualWisdomLab/clearfolio" not in text


def test_review_fix_scheduler_retries_same_head_after_one_hour() -> None:
    """A blocked head can be retried on the next hourly cycle, not a day later."""
    text = _workflow_text()

    retry_block = text.split("retry_hours:", maxsplit=1)[1].split(
        "autofix_workflow:", maxsplit=1
    )[0]
    assert 'default: "1"' in retry_block
    assert "inputs.retry_hours || '1'" in text
    assert "inputs.retry_hours || '24'" not in text


def test_review_fix_scheduler_remains_bounded_and_single_flight() -> None:
    """Higher cadence never expands mutation volume or parallel execution."""
    text = _workflow_text()

    dispatch_block = text.split("max_dispatches:", maxsplit=1)[1].split(
        "target_repository:", maxsplit=1
    )[0]
    assert 'default: "1"' in dispatch_block
    assert "cancel-in-progress: true" in text
    assert "MAX_DISPATCHES" in text
