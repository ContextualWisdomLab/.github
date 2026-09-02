"""Contracts for event-driven Required OpenCode Review wake reconciliation."""

from pathlib import Path

REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")


def _required() -> str:
    """Return only current-head formal-verdict admission."""
    text = REQUIRED.read_text(encoding="utf-8")
    return text.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]


def _wake() -> str:
    """Return only authenticated formal-receipt wake."""
    text = DISPATCH.read_text(encoding="utf-8")
    return text.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1].split("\n      - name: Publish repository_dispatch OpenCode status\n", 1)[0]


def test_required_verdict_admission_has_no_repository_authored_wait_allocation() -> None:
    """Missing verdict fails closed after authoritative reads, not elapsed time."""
    step = _required()
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "max_poll_transport_failures", "sleep ", "timeout "):
        assert token not in step


def test_dispatch_receipt_wake_is_one_exact_state_transition() -> None:
    """A formal receipt never introduces a retry, sleep, transport, or review-read loop."""
    step = _wake()
    for token in ("for attempt", "seq 1", "sleep ", "timeout ", "/12", "--paginate"):
        assert token not in step
    assert "pull_requests // []" in step
    assert "rerun-failed-jobs" in step


def test_workflow_run_completion_closes_review_before_failure_race() -> None:
    """Failed completion reruns only when newer formal exact-head evidence exists."""
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    job = scheduler.split("  reconcile-opencode-required-verdict:\n", 1)[1].split("\n  scan-pr-queue:\n", 1)[0]
    assert "github.event_name == 'workflow_run'" in job
    assert "github.event.workflow_run.name == 'Required OpenCode Review'" in job
    assert "github.event.workflow_run.conclusion == 'failure'" in job
    assert "github.event.workflow_run.run_started_at" in job
    assert "review_submitted_at" in job and "fromdateiso8601" in job
    assert "rerun-failed-jobs" in job
    for token in ("for attempt", "while :; do", "sleep ", "timeout "):
        assert token not in job
