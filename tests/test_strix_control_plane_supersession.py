"""Regression contract for race-safe Strix predecessor-run supersession."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
SCHEDULER_WORKFLOW = ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"
SCHEDULER_SOURCE = ROOT / "scripts" / "ci" / "pr_review_merge_scheduler.py"


def test_strix_does_not_use_unordered_native_same_pr_cancellation() -> None:
    """Delayed PR events must not be able to cancel a newer live-head scan."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    pre_jobs = workflow.split("jobs:", 1)[0]

    # GitHub does not guarantee concurrency-group ordering. A PR-number-only
    # workflow-level cancel-in-progress group can therefore let a delayed old
    # synchronize/closed delivery cancel the newer run before any live-head
    # validation executes. Keep Strix free of that unsafe control-plane shortcut.
    assert "strix-workflow-${{" not in pre_jobs
    assert "cancel-in-progress:" not in pre_jobs

    # The old runner-backed cleanup job caused the Strix workflow itself to stay
    # active after its authoritative scan job was cancelled, which in turn made
    # same-head reruns return HTTP 403. Retirement therefore remains required.
    assert "cancel-superseded-pr-runs:" not in workflow


def test_strix_stale_run_retirement_is_owned_by_live_head_validating_scheduler() -> None:
    """Use the trusted scheduler to cancel predecessor heads after live PR lookup."""
    workflow = SCHEDULER_WORKFLOW.read_text(encoding="utf-8")
    source = SCHEDULER_SOURCE.read_text(encoding="utf-8")

    trigger_contract = workflow.split("concurrency:", 1)[0]
    assert "pull_request_target:" in trigger_contract
    assert "synchronize" in trigger_contract
    assert "closed" in trigger_contract

    scan_job = workflow.split("  scan-pr-queue:", 1)[1].split("\n  org-queue-sweep:", 1)[0]
    assert "actions: write" in scan_job

    assert "cancel_stale_pr_runs(repo, pr, dry_run=dry_run)" in source
    cancel_function = source.split("def cancel_stale_pr_runs(", 1)[1].split("\ndef ", 1)[0]
    assert 'require_github_actions_control_actor("force-cancel-stale-pr-runs")' in cancel_function
    assert "run_ids = stale_pr_run_ids(repo, pr)" in cancel_function
    assert "force_cancel_workflow_runs(repo, run_ids)" in cancel_function


def test_strix_preserves_provider_serialization_after_cleanup_retirement() -> None:
    """Keep the expensive scan serialized by repository/event class."""
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    strix_job = workflow.split("  strix:", 1)[1]
    concurrency = strix_job.split("concurrency:", 1)[1].split("runs-on:", 1)[0]

    assert "github.event.client_payload.target_repository" in concurrency
    assert "github.event.pull_request.base.repo.full_name" in concurrency
    assert "github.repository" in concurrency
    assert "cancel-in-progress: false" in concurrency
    assert "github.event.pull_request.number" not in concurrency
