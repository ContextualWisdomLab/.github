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
    assert "workflow_call:" in header
    assert 'cron: "*/5 * * * *"' in header
    assert "workflow_dispatch:" not in header
    assert "permissions:\n  contents: read" in header
    assert "contents: write" not in header
    assert text.count("runs-on: ubuntu-24.04") == 3
    assert text.count(CHECKOUT_PIN) == 3
    assert "ubuntu-latest" not in text
    assert "actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8" not in text

    local, sweep = jobs.split("\n  sweep-organization-agent-mentions:\n", 1)
    assert "route-local-agent-mention:" in local
    assert "github.repository == 'ContextualWisdomLab/.github'" in local
    for permission in (
        "actions: read",
        "contents: write",
        "issues: write",
        "pull-requests: read",
    ):
        assert f"      {permission}" in local
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


def test_native_reusable_route_reuses_exact_called_source_and_live_github_data() -> None:
    """Sibling callers pass identities while the central route reloads live objects."""

    text = WORKFLOW.read_text(encoding="utf-8")
    native = text.split("\n  route-native-agent-mention:\n", 1)[1].split(
        "\n  sweep-organization-agent-mentions:\n", 1
    )[0]

    assert "github.event_name == 'workflow_call'" in native
    assert "github.repository_owner == 'ContextualWisdomLab'" in native
    assert "group: ${{ github.workflow }}-${{ github.repository }}-${{ inputs.pull_request_number }}" in native
    assert "cancel-in-progress: true" in native
    assert 'json.loads(base64.urlsafe_b64decode' in native
    assert '["job_workflow_ref"]' in native
    assert "agent-mention-router\\.yml@([0-9a-f]{40})" in native
    assert "repository: ContextualWisdomLab/.github" in native
    assert "ref: ${{ steps.trusted_source.outputs.sha }}" in native
    assert 'test "$(git rev-parse HEAD)" = "$EXPECTED_SHA"' in native
    assert "test ! -L scripts/ci/opencode_repository_dispatch_targets.json" in native
    assert "${{ job.workflow_repository }}" not in native
    assert "${{ job.workflow_sha }}" not in native
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PULL_REQUEST_NUMBER}"' in native
    assert 'gh api "repos/${TARGET_REPOSITORY}/issues/comments/${SOURCE_COMMENT_ID}"' in native
    assert "scripts/ci/opencode_repository_dispatch_targets.json" in native
    assert "Central OpenCode repository allowlist mirror is unavailable" in native
    assert '.targets | join(",")' in native
    assert "OPENCODE_REPOSITORY_DISPATCH_TARGETS: ${{ vars." not in native
    assert "PR_REVIEW_MERGE_TOKEN" not in native
    assert "OPENCODE_APPROVE_TOKEN" not in native
    assert 'router_token="${OPENCODE_APP_TOKEN:-}"' in native
    assert "actual_issue_url" in native
    assert "agent_mention_router.py" in native
    assert "sleep " not in native
    assert "agent_mention_sweep.py" not in native


def test_app_token_exchange_is_one_shared_shell_contract() -> None:
    """Native and sweep routes share one bounded OIDC exchange implementation."""

    text = WORKFLOW.read_text(encoding="utf-8")
    exchange = ROOT / "scripts" / "ci" / "exchange_opencode_app_token.sh"
    shell = exchange.read_text(encoding="utf-8")

    assert text.count("bash scripts/ci/exchange_opencode_app_token.sh") == 2
    assert text.count("exchange_github_app_token") == 0
    assert shell.count("exchange_github_app_token") == 1
    assert "--connect-timeout 10 --max-time 30" in shell
    assert "OPENCODE_APP_TOKEN=" in shell


def test_quality_workflow_measures_exact_files_without_module_name_warnings() -> None:
    """Coverage includes the two script paths instead of treating paths as modules."""

    text = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    coverage_config = text.split("[run]\n", 1)[1].split("[report]\n", 1)[0]
    assert "include =" in coverage_config
    assert "source =" not in coverage_config
    assert "scripts/ci/agent_mention_router.py" in coverage_config
    assert "scripts/ci/agent_mention_sweep.py" in coverage_config
