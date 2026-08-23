"""Supply-chain contract for the reusable PR-review autofix scheduler."""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "pr-review-fix-scheduler.yml"


def _workflow_text() -> str:
    """Read the reusable scheduler workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_reusable_scheduler_validates_called_workflow_identity_before_checkout() -> None:
    """Missing workflow identity must fail before checkout can use defaults."""
    workflow = _workflow_text()
    guard = workflow.index("Resolve immutable called-workflow source")
    checkout = workflow.index("Checkout immutable called-workflow source")

    assert guard < checkout
    # job.workflow_repository/workflow_sha/workflow_ref/workflow_file_path are
    # not real Actions context properties (actionlint flags them as undefined
    # on the `job` object). github.workflow_ref/github.workflow_sha are real,
    # documented properties, but for a `workflow_call` target they reflect
    # the top-level CALLING workflow, not this reusable workflow's own file
    # (GitHub exposes a called reusable workflow's own ref/sha only via the
    # OIDC job_workflow_ref claim). Every caller uses a local, same-repo
    # `uses: ./...`, so caller and callee share one commit: github.repository
    # is the correct identity check, and github.workflow_sha is still the
    # correct commit to trust for that same-repo call.
    assert "CALLER_REPOSITORY: ${{ github.repository }}" in workflow
    assert "WORKFLOW_SHA: ${{ github.workflow_sha }}" in workflow
    assert '[ "$CALLER_REPOSITORY" != "$expected_repository" ]' in workflow
    assert "${{ job.workflow_repository }}" not in workflow
    assert "${{ job.workflow_sha }}" not in workflow
    assert "${{ job.workflow_ref }}" not in workflow
    assert "${{ job.workflow_file_path }}" not in workflow
    assert "${{ github.workflow_ref }}" not in workflow
    assert 'expected_repository="ContextualWisdomLab/.github"' in workflow
    assert 'expected_file=".github/workflows/pr-review-fix-scheduler.yml"' in workflow
    assert '[[ "$WORKFLOW_SHA" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert "repository: ${{ steps.trusted_source.outputs.repository }}" in workflow
    assert "ref: ${{ steps.trusted_source.outputs.sha }}" in workflow


def test_reusable_scheduler_verifies_checked_out_called_workflow_sha() -> None:
    """The checked-out commit must equal the validated called-workflow SHA."""
    workflow = _workflow_text()
    verification = workflow.index("Verify immutable called-workflow checkout")
    self_test = workflow.index("Self-test fix scheduler contract")

    assert verification < self_test
    assert 'actual_sha="$(git rev-parse HEAD)"' in workflow
    assert '[ "$actual_sha" != "$EXPECTED_SHA" ]' in workflow
    assert '[ ! -f "$EXPECTED_FILE" ] || [ -L "$EXPECTED_FILE" ]' in workflow


def test_reusable_scheduler_source_is_not_caller_input_controlled() -> None:
    """No caller-supplied ref or ordinary caller GitHub SHA selects trusted code."""
    workflow = _workflow_text()
    assert "inputs.canonical_ref" not in workflow
    assert "github.event.client_payload.canonical_ref" not in workflow
    assert "ref: ${{ env.CANONICAL_REF }}" not in workflow
    assert "ref: ${{ github.sha }}" not in workflow
    assert "ref: ${{ github.workflow_sha }}" not in workflow


def test_deprecated_canonical_ref_input_is_accepted_but_never_consumed() -> None:
    """Existing callers can upgrade pins without controlling privileged source."""
    workflow = _workflow_text()
    declaration = workflow.split("canonical_ref:", 1)[1].split(
        "repository_dispatch:", 1
    )[0]

    assert "Deprecated compatibility input" in declaration
    assert "ignored" in declaration
    assert 'default: ""' in declaration
    assert workflow.count("canonical_ref") == 1


def test_reusable_scheduler_retains_least_privilege_and_bounded_dispatch() -> None:
    """Source pinning does not broaden token scope or queue fan-out."""
    workflow = _workflow_text()
    assert "contents: write" not in workflow
    assert "pull-requests: write" not in workflow
    assert "MAX_DISPATCHES:" in workflow
    assert "RETRY_HOURS:" in workflow
    assert "cancel-in-progress: true" in workflow


def test_reusable_scheduler_bounds_both_oidc_exchange_requests() -> None:
    """OIDC and app-token exchange network calls must fail within bounded time."""
    workflow = _workflow_text()
    exchange = workflow.split(
        "- name: Exchange OpenCode app token for scheduler mutations", 1
    )[1].split("- name: Resolve immutable called-workflow source", 1)[0]

    assert exchange.count("curl -fsS \\") == 2
    oidc_request = exchange.split('if ! oidc_response="$(' , 1)[1].split(
        ')"; then', 1
    )[0]
    app_token_request = exchange.split('if ! token_response="$(' , 1)[1].split(
        ')"; then', 1
    )[0]
    for request in (oidc_request, app_token_request):
        assert request.count("--connect-timeout 10 \\") == 1
        assert request.count("--max-time 30 \\") == 1
