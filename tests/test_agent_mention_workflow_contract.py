"""Static least-privilege and trigger contract for agent mention automation."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router.yml"
QUALITY_WORKFLOW = (
    ROOT / ".github" / "workflows" / "agent-mention-router-quality-ci.yml"
)
CHECKOUT_PIN = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"


def test_workflow_uses_local_event_and_central_sweep_with_job_scoped_writes() -> None:
    """The router is central-only, scheduled, and least-privileged."""

    text = WORKFLOW.read_text(encoding="utf-8")
    header, jobs = text.split("\njobs:\n", 1)
    assert "issue_comment:" in header
    assert "pull_request_review_comment:" in header
    assert "pull_request_review:" in header
    assert 'cron: "*/5 * * * *"' in header
    assert "github.event.issue.number || github.event.pull_request.number" in text
    assert "contains(github.event.comment.body, '@cwl-noema-review')" not in text
    assert "workflow_dispatch:" not in header
    assert "permissions:\n  contents: read" in header
    assert "contents: write" not in header
    assert text.count("runs-on: ubuntu-24.04") == 2
    assert text.count(CHECKOUT_PIN) == 2
    assert "ubuntu-latest" not in text
    assert "actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8" not in text

    local, sweep = jobs.split("\n  sweep-organization-agent-mentions:\n", 1)
    assert "route-local-agent-mention:" in local
    assert "github.repository == 'ContextualWisdomLab/.github'" in local
    for permission in (
        "actions: read",
        "contents: write",
        "issues: write",
        "pull-requests: write",
    ):
        assert f"      {permission}" in local
    assert "reactions: write" not in local
    assert "reactions:" not in local
    assert "ref: ${{ github.event.repository.default_branch }}" in local
    assert "TARGET_REPOSITORY_TOKEN: ${{ github.token }}" in local
    assert "conversation_comments" not in local

    for permission in ("actions: read", "contents: write", "id-token: write"):
        assert f"      {permission}" in sweep
    assert "github.repository == 'ContextualWisdomLab/.github'" in sweep
    assert "github.event_name == 'schedule'" in sweep
    assert "github.event_name == 'workflow_dispatch'" not in sweep
    assert "secrets.PR_REVIEW_MERGE_TOKEN" in sweep
    assert "secrets.OPENCODE_APPROVE_TOKEN" in sweep
    assert "TARGET_REPOSITORY_SOURCE" in sweep
    assert "AGENT_DISPATCH_TOKEN: ${{ github.token }}" in sweep
    assert "agent_mention_sweep.py" in sweep
    helper = (ROOT / "scripts" / "ci" / "agent_mention_router.py").read_text(
        encoding="utf-8"
    )
    assert "mention_reaction_path" in helper
    assert "/pulls/comments/" in helper
    assert "SOURCE_KIND_REVIEW_COMMENT" in helper
    assert "ADD_REVIEW_REACTION_MUTATION" in helper
    assert "addReaction" in helper
    assert "graphql_eyes_reaction_succeeded" in helper
    assert "graphql_error_already_reacted" in helper


def test_quality_workflow_measures_exact_files_without_module_name_warnings() -> None:
    """Coverage includes the two script paths instead of treating paths as modules."""

    text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    coverage_config = text.split("[run]\n", 1)[1].split("[report]\n", 1)[0]
    assert "include =" in coverage_config
    assert "source =" not in coverage_config
    assert "scripts/ci/agent_mention_router.py" in coverage_config
    assert "scripts/ci/agent_mention_sweep.py" in coverage_config
