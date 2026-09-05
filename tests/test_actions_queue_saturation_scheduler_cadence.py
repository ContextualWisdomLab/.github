"""Regression contract for the organization scheduler queue-saturation repair."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def test_org_queue_sweep_is_removed() -> None:
    """Native events own progress without an organization-wide polling job."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "org-queue-sweep" not in workflow
    assert "org_sweep" not in workflow
    assert "ORG_SWEEP" not in workflow


def test_repository_scheduler_keeps_event_driven_wakes() -> None:
    """Capacity repair must preserve event-driven admission rather than polling only."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "pull_request_review:" in workflow
    assert "workflow_run:" not in workflow
    assert "repository_dispatch:" in workflow


def test_scan_pr_queue_keeps_offset_daily_missed_event_recovery() -> None:
    """scan-pr-queue's own repository-local heartbeat must not be dropped.

    scan-pr-queue's own cron is the sole periodic fallback for this
    repository's PR queue after a genuinely missed native event.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '- cron: "47 3 * * *"' in workflow
    assert '- cron: "30 * * * *"' not in workflow
    assert '*/30 * * * *' not in workflow
    schedule_block = workflow.split("  schedule:", 1)[1].split(
        "  repository_dispatch:", 1
    )[0]
    assert schedule_block.count('- cron:') == 1


def test_required_check_completions_are_owned_by_auto_merge() -> None:
    """Required-check completion must not fan out another scheduler run."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_run:" not in workflow
    assert "auto-merge handles required-check completion" in workflow
