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


def _concurrency_block(job: str) -> str:
    """Return the job-scoped concurrency mapping before ``runs-on``."""

    if "    concurrency:\n" not in job:
        return ""
    start = job.index("    concurrency:\n")
    end = job.index("\n    runs-on:", start)
    return job[start:end]


def test_interactive_mentions_run_without_a_replacing_concurrency_queue() -> None:
    """Every trusted mention receives a run while sweeps stay single-flight."""

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

    assert not any(line.startswith("concurrency:") for line in header.splitlines())
    assert _concurrency_block(local_job) == ""
    assert _concurrency_block(sweep_job) == (
        "    concurrency:\n"
        "      group: review-agent-mention-router-sweep-${{ github.repository }}\n"
        "      cancel-in-progress: false"
    )


def test_interactive_route_has_no_unsupported_or_replacing_queue_controls() -> None:
    """Interactive work is neither invalid YAML nor a replaceable pending run."""

    workflow = WORKFLOW.read_text(encoding="utf-8")
    local_job = _job_block(
        workflow,
        "route-local-agent-mention",
        "sweep-organization-agent-mentions",
    )
    assert _concurrency_block(local_job) == ""
    assert "queue: max" not in local_job
    assert "cancel-in-progress" not in local_job
