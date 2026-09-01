"""Regression coverage for review-event scheduler wake behavior."""

from tests.test_required_workflow_queue_contract import workflow_text


def test_review_events_can_dispatch_after_threads_are_resolved() -> None:
    """Let the scheduler dispatch OpenCode when a review event clears its last blocker."""
    workflow = workflow_text("pr-review-merge-scheduler.yml")
    scan_job = workflow.split("  scan-pr-queue:", 1)[1].split("  org-queue-sweep:", 1)[0]

    assert "github.event_name == 'pull_request_review'" in scan_job.split(
        "TRIGGER_REVIEWS:", 1
    )[1].splitlines()[0]
