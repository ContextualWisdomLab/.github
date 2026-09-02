"""Contracts for event-driven Required OpenCode Review wake reconciliation."""

from pathlib import Path


REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
SCHEDULER = Path(".github/workflows/pr-review-merge-scheduler.yml")


def _required_verdict_step() -> str:
    """Return only the current-head formal-verdict admission step."""
    workflow = REQUIRED.read_text(encoding="utf-8")
    return workflow.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]


def _dispatch_wake_step() -> str:
    """Return only the exact-run wake step in the privileged dispatch."""
    workflow = DISPATCH.read_text(encoding="utf-8")
    return workflow.split(
        "      - name: Wake exact-head required OpenCode workflow\n", 1
    )[1].split("\n      - name: Publish repository_dispatch OpenCode status\n", 1)[0]


def test_required_verdict_admission_has_no_repository_authored_wait_allocation() -> None:
    """A missing verdict fails closed after authoritative state reads, not elapsed time."""
    step = _required_verdict_step()
    for token in (
        "while :; do",
        "poll_interval_seconds",
        "poll_deadline_epoch",
        "max_poll_transport_failures",
        "sleep ",
        "timeout ",
    ):
        assert token not in step


def test_dispatch_wake_has_no_fixed_retry_delay_or_transport_deadline() -> None:
    """The receipt path performs one exact-state transition without a retry budget."""
    step = _dispatch_wake_step()
    for token in ("for attempt", "seq 1", "sleep ", "timeout ", "/12"):
        assert token not in step
    assert "run_started_at" in step
    assert "submitted_at" in step
    assert "rerun-failed-jobs" in step


def test_workflow_run_completion_reconciles_new_formal_review_evidence() -> None:
    """GitHub's completed-workflow event closes the review-before-failure race."""
    scheduler = SCHEDULER.read_text(encoding="utf-8")
    assert 'workflows: ["Required OpenCode Review", "Strix Security Scan"]' in scheduler
    assert "reconcile-opencode-required-verdict:" in scheduler
    reconciliation = scheduler.split("  reconcile-opencode-required-verdict:\n", 1)[1].split(
        "\n  ", 1
    )[0]
    assert "github.event_name == 'workflow_run'" in reconciliation
    assert "github.event.workflow_run.name == 'Required OpenCode Review'" in reconciliation
    assert "github.event.workflow_run.conclusion == 'failure'" in reconciliation
    assert "github.event.workflow_run.run_started_at" in reconciliation
    assert "submitted_at" in reconciliation
    assert "rerun-failed-jobs" in reconciliation
    for token in ("for attempt", "while :; do", "sleep ", "timeout "):
        assert token not in reconciliation
