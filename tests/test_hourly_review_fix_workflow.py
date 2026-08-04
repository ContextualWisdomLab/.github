"""Contract tests for the autonomous hourly review-feedback repair loop."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_review_fix_scheduler_runs_hourly_with_bounded_retry() -> None:
    """Keep feedback repair hourly, off minute zero, and bounded per PR head."""
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "pr-review-fix-scheduler.yml"
    ).read_text(encoding="utf-8")

    schedule_contract = workflow.split("schedule:", 1)[1].split("concurrency:", 1)[0]
    retry_contract = workflow.split("retry_hours:", 1)[1].split(
        "autofix_workflow:", 1
    )[0]

    assert 'cron: "23 * * * *"' in schedule_contract
    assert 'cron: "23 */2 * * *"' not in schedule_contract
    assert 'default: "1"' in retry_contract
    assert (
        "RETRY_HOURS: ${{ github.event.client_payload.retry_hours || "
        "inputs.retry_hours || '1' }}"
    ) in workflow
    assert (
        "MAX_DISPATCHES: ${{ github.event.client_payload.max_dispatches || "
        "inputs.max_dispatches || '1' }}"
    ) in workflow
