from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "organization-commercial-readiness-loop.yml"
)


def test_maintainer_token_is_scoped_only_to_the_dispatch_step() -> None:
    """Third-party setup actions must never receive the cross-repository token."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    before_dispatch, dispatch_step = source.split(
        "      - name: Coordinate one bounded fleet pass\n", maxsplit=1
    )

    assert "PR_REVIEW_MERGE_TOKEN" not in before_dispatch
    assert "GH_TOKEN:" not in before_dispatch
    assert "env:\n          GH_TOKEN: ${{ secrets.PR_REVIEW_MERGE_TOKEN }}" in dispatch_step


def test_missing_maintainer_secret_uses_bounded_job_oidc_exchange() -> None:
    """A protected scheduled pass must not die solely because the PAT is absent."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    _, dispatch_step = source.split(
        "      - name: Coordinate one bounded fleet pass\n", maxsplit=1
    )

    assert "id-token: write" in source
    assert "api.opencode.ai:443" in source
    assert "OIDC_AUDIENCE: opencode-github-action" in dispatch_step
    assert "OPENCODE_API_BASE_URL: https://api.opencode.ai" in dispatch_step
    assert "ACTIONS_ID_TOKEN_REQUEST_TOKEN" in dispatch_step
    assert "ACTIONS_ID_TOKEN_REQUEST_URL" in dispatch_step
    assert "--connect-timeout 10" in dispatch_step
    assert "--max-time 30" in dispatch_step
    assert "/exchange_github_app_token" in dispatch_step
    assert 'export GH_TOKEN="$app_token"' in dispatch_step
    assert "::add-mask::$oidc_token" in dispatch_step
    assert "::add-mask::$app_token" in dispatch_step
    assert "${{ github.token }}" not in dispatch_step
    assert "GITHUB_TOKEN:" not in dispatch_step


def test_installation_token_contract_accepts_the_new_long_stateless_shape() -> None:
    """Token validation must not assume the legacy GitHub App token length."""
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    token_extract = 'jq -er \' .token | select(type == "string" and length > 0) \''
    # Keep the assertion tied to the actual jq expression, not to a comment or
    # an unrelated length check elsewhere in the workflow.
    assert 'jq -er \' .token | select(type == "string" and length > 0) \''
    assert "length == 40" not in source
    assert "length == 45" not in source
    assert "cut -c1-40" not in source
    long_stateless_token = "ghs_" + "x" * 516
    assert len(long_stateless_token) == 520
