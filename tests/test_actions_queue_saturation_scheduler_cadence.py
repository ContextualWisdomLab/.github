"""Regression contract for the organization scheduler queue-saturation repair."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def test_org_queue_sweep_is_hourly_not_quarter_hourly() -> None:
    """The expensive org sweep must not self-amplify a saturated Actions queue."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '- cron: "0 * * * *"' in workflow or "- cron: '0 * * * *'" in workflow
    assert '*/15 * * * *' not in workflow


def test_repository_scheduler_keeps_event_driven_wakes() -> None:
    """Capacity repair must preserve event-driven admission rather than polling only."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "pull_request_review:" in workflow
    assert "workflow_run:" in workflow
    assert "repository_dispatch:" in workflow
