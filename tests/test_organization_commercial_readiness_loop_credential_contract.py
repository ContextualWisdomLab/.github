from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "organization-commercial-readiness-loop.yml"
)


def test_central_schedule_has_no_branch_selected_or_reviewer_credential_path() -> None:
    """The fleet coordinator uses schedule-bound maintainer or App authority."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "workflow_dispatch:" not in source
    assert "GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in source
    assert "steps.opencode_app_token.outputs.token" not in source
    assert "id-token: write" in source
    assert "OIDC_AUDIENCE: opencode-github-action" in source
    assert "https://api.opencode.ai/exchange_github_app_token" not in source
    assert '"${OPENCODE_API_BASE_URL}/exchange_github_app_token"' in source
    assert "persist-credentials: false" in source
    assert "OPENCODE_APPROVE_TOKEN" not in source
    assert "|| github.token" not in source
    assert "DRY_RUN" not in source
    assert "inputs.dry_run" not in source


def test_opencode_exchange_fails_closed_without_wasting_or_exposing_credentials() -> None:
    """Malformed exchanges diagnose safely and the preferred secret skips OIDC."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")

    coordinate = source.split(
        "      - name: Coordinate one bounded fleet pass\n", maxsplit=1
    )[1]
    assert 'if [ -z "${GH_TOKEN:-}" ]; then' in coordinate
    assert 'export GH_TOKEN="$app_token"' in coordinate
    assert 'if ! oidc_token="$(jq -r' in source
    assert 'if ! app_token="$(jq -r' in source
    assert "OIDC token response was malformed" in source
    assert "app token response was malformed" in source
    assert 'echo "::add-mask::$oidc_token"' in source
    assert coordinate.count("--connect-timeout 10") == 2
    assert coordinate.count("--max-time 30") == 2
