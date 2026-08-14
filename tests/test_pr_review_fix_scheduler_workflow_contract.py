"""Workflow-level contract for the bounded PR review repair scheduler."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/pr-review-fix-scheduler.yml")


def workflow_text() -> str:
    """Return the canonical workflow source used by the scheduler."""

    return WORKFLOW.read_text(encoding="utf-8")


def test_review_fix_scheduler_runs_once_per_hour() -> None:
    """Every open-PR queue receives a fixed hourly repair opportunity."""

    text = workflow_text()
    assert 'cron: "23 * * * *"' in text
    assert 'cron: "23 */2 * * *"' not in text


def test_same_head_autofix_retry_default_is_one_hour() -> None:
    """A failed or incomplete repair can be retried on the next hourly sweep."""

    text = workflow_text()
    retry_block = text.split("retry_hours:", maxsplit=1)[1].split(
        "autofix_workflow:", maxsplit=1
    )[0]
    assert 'default: "1"' in retry_block
    assert "inputs.retry_hours || '1'" in text
