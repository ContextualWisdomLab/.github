"""Regression contract for consolidated Noema quality-run retirement."""

from tests.test_required_workflow_queue_contract import (
    workflow_level_cancels_in_progress,
)
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT
    / ".github"
    / "workflows"
    / "agent-review-runtime-quality-ci.yml"
)


def test_noema_token_lifetime_quality_ci_retires_superseded_pr_runs() -> None:
    """Keep one authoritative repository/PR lineage for the quality gate."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    concurrency_contract = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]

    assert "concurrency:" in workflow
    assert "github.repository" in concurrency_contract
    assert "github.event.pull_request.number" in concurrency_contract
    assert "github.event.pull_request.head.sha" not in concurrency_contract
    assert "github.sha" not in concurrency_contract
    assert "github.ref" not in concurrency_contract
    assert workflow_level_cancels_in_progress(workflow)
