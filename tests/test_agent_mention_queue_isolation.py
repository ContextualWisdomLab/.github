"""Regression contracts for isolated review-agent mention queues."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router.yml"


def _job_block(workflow: str, job_name: str, next_job_name: str | None) -> str:
    """Return one top-level workflow job bounded by the following job."""

    jobs = workflow.split("\njobs:\n", 1)[1]
    start = jobs.index(f"  {job_name}:\n")
    if next_job_name is None:
        return jobs[start:]
    end = jobs.index(f"\n  {next_job_name}:\n", start)
    return jobs[start:end]


def test_interactive_mentions_and_sweeps_use_independent_queues() -> None:
    """A scheduled sweep cannot replace a pending trusted mention request."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    header = workflow.split("\njobs:\n", 1)[0]
    local_job = _job_block(
        workflow,
        "route-local-agent-mention",
        "sweep-organization-agent-mentions",
    )
    sweep_job = _job_block(
        workflow,
        "sweep-organization-agent-mentions",
        None,
    )

    assert "concurrency:\n" in header
    assert "group: review-agent-mention-router-${{ github.repository }}" in header
    assert "cancel-in-progress: false" in header
    assert "concurrency:" not in local_job
    assert "concurrency:" not in sweep_job


def test_interactive_queue_retains_pending_requests_without_cancellation() -> None:
    """The bounded interactive queue retains work and never cancels in progress."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    local_job = _job_block(
        workflow,
        "route-local-agent-mention",
        "sweep-organization-agent-mentions",
    )
    assert "queue: max" not in workflow
    assert "cancel-in-progress: true" not in workflow
