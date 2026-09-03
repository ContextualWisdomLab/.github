"""Regression contract for Noema token-lifetime PR run retirement."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "noema-token-lifetime-quality-ci.yml"


def test_noema_token_lifetime_quality_ci_retires_superseded_pr_runs() -> None:
    """Keep one authoritative PR/head lineage for the token-lifetime quality gate."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "concurrency:" in workflow
    concurrency_contract = workflow.split("concurrency:", 1)[1].split(
        "permissions:", 1
    )[0]
    assert "github.event.pull_request.base.repo.full_name" in concurrency_contract
    assert "github.event.pull_request.number" in concurrency_contract
    assert "github.event.pull_request.head.sha" not in concurrency_contract
    assert "github.sha" not in concurrency_contract
    assert "cancel-in-progress: true" in concurrency_contract
