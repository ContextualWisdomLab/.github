"""Regression contract for the organization scheduler queue-saturation repair."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"


def test_org_queue_sweep_is_daily_recovery_not_hourly_polling() -> None:
    """Native events own normal progress; the expensive sweep only recovers gaps."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '- cron: "17 3 * * *"' in workflow
    assert '- cron: "0 * * * *"' not in workflow
    assert '*/15 * * * *' not in workflow


def test_org_queue_sweep_wall_clock_fallback_matches_daily_cadence() -> None:
    """Fallback rotation and its maintenance comments must match daily cadence."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert workflow.count("$(date -u +%s) / 86400") == 2
    assert "$(date -u +%s) / 3600" not in workflow
    assert "$(date -u +%s) / 900" not in workflow
    assert "900s window" not in workflow
    assert "900s)" not in workflow
    assert "pending */15 sweep" not in workflow


def test_repository_scheduler_keeps_event_driven_wakes() -> None:
    """Capacity repair must preserve event-driven admission rather than polling only."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in workflow
    assert "pull_request_review:" in workflow
    assert "workflow_run:" not in workflow
    assert "repository_dispatch:" in workflow


def test_scan_pr_queue_keeps_offset_daily_missed_event_recovery() -> None:
    """scan-pr-queue's own repository-local heartbeat must not be dropped.

    org-queue-sweep excludes ContextualWisdomLab/.github from its target
    list by name, so scan-pr-queue's own cron is the sole periodic fallback
    for this repository's PR queue after a genuinely missed native event.
    Keep one low-frequency fallback offset from the organization recovery.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert '- cron: "47 3 * * *"' in workflow
    assert '- cron: "30 * * * *"' not in workflow
    assert '*/30 * * * *' not in workflow
    schedule_block = workflow.split("  schedule:", 1)[1].split(
        "  repository_dispatch:", 1
    )[0]
    assert schedule_block.count('- cron:') == 2


def test_required_check_completions_are_owned_by_auto_merge() -> None:
    """Required-check completion must not fan out another scheduler run."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_run:" not in workflow
    assert "auto-merge handles required-check completion" in workflow
