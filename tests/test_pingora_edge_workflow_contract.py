"""Contract tests for organization-wide Pingora enforcement."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "opencode-review.yml"


def test_required_workflow_enforces_pingora_without_executing_pr_content() -> None:
    """The trusted bootstrap must scan API evidence from immutable central code."""

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull-requests: read" in text
    assert "job.workflow_repository" in text
    assert "job.workflow_sha" in text
    assert "repository: ${{ steps.trusted_source.outputs.repository }}" in text
    assert "ref: ${{ steps.trusted_source.outputs.sha }}" in text
    assert "persist-credentials: false" in text
    assert "scripts/ci/pingora_edge_policy.py" in text
    assert '--api-url "https://api.github.com"' in text
    assert "github.event.pull_request.head.sha" in text
    assert "checkout pull-request" not in text.lower()
    assert "secrets:" not in text
