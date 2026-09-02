"""Regression contract for comment-only pull-request review scheduler events."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/pr-review-merge-scheduler.yml")


def test_commented_submitted_review_is_filtered_at_job_boundary() -> None:
    """COMMENTED submissions must skip the runner-backed queue scan entirely."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    scan_job = workflow.split("  scan-pr-queue:", 1)[1].split("  org-queue-sweep:", 1)[0]
    expected_guard = """      (
        github.event_name != 'pull_request_review' ||
        github.event.action != 'submitted' ||
        github.event.review.state != 'commented'
      ) &&
"""
    assert expected_guard in scan_job.split("    runs-on:", 1)[0]


def test_actionable_review_event_triggers_remain_registered() -> None:
    """Keep submitted approvals/change requests and dismissed reviews observable."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "  pull_request_review:\n    types: [submitted, dismissed]" in workflow
