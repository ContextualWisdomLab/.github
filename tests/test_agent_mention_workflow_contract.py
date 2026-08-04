"""Static least-privilege and trigger contract for agent mention automation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router.yml"


def test_workflow_uses_local_event_and_central_sweep_with_job_scoped_writes() -> None:
    """The router is central-only, organization-wide, and least-privileged."""

    text = WORKFLOW.read_text(encoding="utf-8")
    header, jobs = text.split("\njobs:\n", 1)
    assert "issue_comment:" in header
    assert 'cron: "*/5 * * * *"' in header
    assert "workflow_dispatch:" in header
    assert "permissions:\n  contents: read" in header
    assert "contents: write" not in header

    local, sweep = jobs.split("\n  sweep-organization-agent-mentions:\n", 1)
    assert "route-local-agent-mention:" in local
    assert "github.repository == 'ContextualWisdomLab/.github'" in local
    assert (
        "permissions:\n"
        "      contents: write\n"
        "      issues: write\n"
        "      pull-requests: read"
    ) in local
    assert "ref: ${{ github.event.repository.default_branch }}" in local
    assert "TARGET_REPOSITORY_TOKEN: ${{ github.token }}" in local
    assert "conversation_comments" in local

    assert "permissions:\n      contents: write\n      id-token: write" in sweep
    assert "github.repository == 'ContextualWisdomLab/.github'" in sweep
    assert "secrets.PR_REVIEW_MERGE_TOKEN" in sweep
    assert "secrets.OPENCODE_APPROVE_TOKEN" in sweep
    assert "TARGET_REPOSITORY_SOURCE" in sweep
    assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in sweep
    assert "agent_mention_sweep.py" in sweep
