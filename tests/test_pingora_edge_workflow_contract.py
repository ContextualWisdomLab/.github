"""Contract tests for organization-wide Pingora enforcement."""

from pathlib import Path


ROOT = Path(__file__).parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "opencode-review.yml"


def test_required_workflow_enforces_pingora_without_executing_pr_content() -> None:
    """The trusted bootstrap must scan API evidence from immutable central code."""

    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull-requests: read" in text
    assert "JOB_CONTEXT_JSON: ${{ toJSON(job) }}" in text
    assert "WORKFLOW_SHA: ${{ github.workflow_sha }}" in text
    assert "WORKFLOW_REF: ${{ github.workflow_ref }}" in text
    assert "GITHUB_CONTEXT_JSON" not in text
    assert 'job_context.get("workflow_sha") or os.environ.get("WORKFLOW_SHA")' in text
    assert 'workflow_ref.partition("@")' in text
    assert 'workflow_repository = "/".join(ref_parts[:2])' in text
    assert 'job_context.get("workflow_repository")' not in text
    assert "TRUSTED_SOURCE_REF: ${{ steps.trusted_source.outputs.sha }}" in text
    assert "repos/ContextualWisdomLab/.github/tarball/${TRUSTED_SOURCE_REF}" in text
    assert "Trusted central policy source ref must resolve to the immutable workflow commit SHA" in text
    assert "actions/checkout" not in text
    assert "scripts/ci/pingora_edge_policy.py" in text
    assert '--api-url "https://api.github.com"' in text
    assert "secrets:" not in text

    # The required workflow must never turn the untrusted PR head into a source
    # checkout ref; it is only an evidence identifier passed to the API scanner.
    assert "ref: ${{ github.event.pull_request.head.sha }}" not in text
    assert 'TRUSTED_SOURCE_REF: ${{ steps.trusted_source.outputs.sha }}' in text
    assert 'tarball/${TRUSTED_SOURCE_REF}' in text

    # The source archive must contain both the workflow and the policy helper,
    # and symlinked replacements must fail before the helper is executed.
    assert '[ ! -f "$trusted_source_dir/$EXPECTED_FILE" ]' in text
    assert '[ -L "$trusted_source_dir/$EXPECTED_FILE" ]' in text
    assert '[ ! -f "$trusted_source_dir/scripts/ci/pingora_edge_policy.py" ]' in text
    assert '[ -L "$trusted_source_dir/scripts/ci/pingora_edge_policy.py" ]' in text
    # The workflow is already pull_request_target-only. Keeping an event
    # expression inside the required bootstrap makes the materialized gate
    # depend on caller event payload fields and violates the bootstrap policy.
    assert "if: ${{ github.event_name == 'pull_request_target' }}" not in text
    assert text.index("Verify immutable central policy source") < text.index(
        "Enforce Cloudflare Pingora edge policy"
    )
