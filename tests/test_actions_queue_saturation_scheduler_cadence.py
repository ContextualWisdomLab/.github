"""Regression contract for the organization scheduler queue-saturation repair."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def test_org_queue_sweep_is_hourly_not_quarter_hourly() -> None:
    """The expensive org sweep must not self-amplify a saturated Actions queue."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '- cron: "0 * * * *"' in workflow or "- cron: '0 * * * *'" in workflow
    assert '*/15 * * * *' not in workflow


def test_org_queue_sweep_wall_clock_fallback_matches_hourly_cadence() -> None:
    """Fallback rotation and its maintenance comments must match hourly cadence."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count("$(date -u +%s) / 3600") == 2
    assert "$(date -u +%s) / 900" not in workflow
    assert "900s window" not in workflow
    assert "900s)" not in workflow
    assert "pending */15 sweep" not in workflow


def test_repository_scheduler_keeps_event_driven_wakes() -> None:
    """Capacity repair must preserve event-driven admission rather than polling only."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "pull_request_review:" in workflow
    assert "workflow_run:" in workflow
    assert "repository_dispatch:" in workflow


def test_scan_pr_queue_heartbeat_is_hourly_and_offset_not_removed() -> None:
    """scan-pr-queue's own repository-local heartbeat must not be dropped.

    org-queue-sweep excludes ContextualWisdomLab/.github from its target
    list by name, so scan-pr-queue's own cron is the sole periodic fallback
    for this repository's PR queue (and for any required check, such as
    Security Scan or SAST Semgrep, with no workflow_run listener anywhere in
    this file). It must be lengthened to hourly for the same capacity reason
    as org-queue-sweep, not deleted, and offset from org-queue-sweep's
    "0 * * * *" tick so the two heartbeats do not collide.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '- cron: "30 * * * *"' in workflow
    assert '*/30 * * * *' not in workflow
    schedule_block = workflow.split("  schedule:", 1)[1].split(
        "  repository_dispatch:", 1
    )[0]
    assert schedule_block.count('- cron:') == 2
