"""Regression contract for Strix predecessor-run supersession."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"


def test_strix_supersedes_same_pr_before_runner_allocation() -> None:
    """Cancel predecessor heads in GitHub's control plane, not a queued runner job."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    pre_jobs = workflow.split("jobs:", 1)[0]
    concurrency = pre_jobs.split("concurrency:", 1)[1].split("permissions:", 1)[0]

    assert "concurrency:" in pre_jobs
    assert "strix-workflow-${{" in concurrency
    assert "github.event.pull_request.base.repo.full_name" in concurrency
    assert "github.event.pull_request.number" in concurrency
    assert "github.event.pull_request.head.sha" not in concurrency
    assert "github.event.action == 'synchronize'" in concurrency
    assert "github.event.action == 'closed'" in concurrency
    assert "cancel-in-progress: ${{" in concurrency
    assert "cancel-superseded-pr-runs:" not in workflow


def test_strix_preserves_provider_serialization_after_runner_free_supersession() -> None:
    """Keep the expensive scan serialized by repository/event class after cleanup removal."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    strix_job = workflow.split("  strix:", 1)[1]
    concurrency = strix_job.split("concurrency:", 1)[1].split("runs-on:", 1)[0]

    assert "github.event.client_payload.target_repository" in concurrency
    assert "github.event.pull_request.base.repo.full_name" in concurrency
    assert "github.repository" in concurrency
    assert "cancel-in-progress: false" in concurrency
    assert "github.event.pull_request.number" not in concurrency
