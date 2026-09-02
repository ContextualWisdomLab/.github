"""Regression contract for Noema reviewer credential lifetime."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "noema-review.yml"
APP_TOKEN_ACTION = (
    "uses: actions/create-github-app-token@"
    "bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0"
)


def _step_block(text: str, name: str) -> str:
    """Return one exact named workflow step without borrowing sibling evidence."""
    marker = f"      - name: {name}\n"
    start = text.index(marker)
    next_step = text.find("\n      - name: ", start + len(marker))
    return text[start:] if next_step < 0 else text[start:next_step]


def test_noema_remints_repository_scoped_app_token_after_model_before_publication() -> None:
    """A long model call must not publish with its predecessor App token."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prepare = _step_block(workflow, "Prepare Noema model verdict")
    refresh = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert APP_TOKEN_ACTION in refresh
    assert "--prepare-verdict-file" in prepare
    assert "--publish-verdict-file" in publish
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in prepare
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in publish
    assert 'export NOEMA_LLM_MODEL="orchestrator/free"' in prepare
    assert "steps.noema_prepare.outputs.prepared == 'true'" in refresh
    assert "steps.noema_credential.outputs.source == 'github-app'" in refresh
    assert "steps.noema_prepare.outputs.prepared == 'true'" in publish


def test_publication_step_uses_fresh_app_and_oidc_tokens_without_authority_fallback() -> None:
    """Publication selects freshly minted scoped authority and rejects central fallback."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    app_refresh = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    oidc_refresh = _step_block(workflow, "Refresh repository-scoped Noema OIDC app token for publication")
    live_publish = _step_block(workflow, "Revalidate live Noema target before publication")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert "owner: ContextualWisdomLab" in app_refresh
    assert "repositories: ${{ steps.noema_credential.outputs.repository }}" in app_refresh
    assert "permission-pull-requests: write" in app_refresh
    assert "permission-contents: read" in app_refresh
    assert "permission-actions: read" in app_refresh
    assert "steps.noema_prepare.outputs.prepared == 'true'" in oidc_refresh
    assert "steps.noema_credential.outputs.source == 'oidc'" in oidc_refresh
    assert "id: noema_oidc_publication_token" in oidc_refresh
    assert "target_repository" in oidc_refresh

    for step in (live_publish, publish):
        assert "steps.noema_github_app_publication_token.outputs.token" in step
        assert "steps.noema_oidc_publication_token.outputs.token" in step
        assert "steps.noema_github_app_token.outputs.token" not in step
        assert "steps.noema_oidc_token.outputs.token" not in step
        assert "secrets.NOEMA_REVIEW_TOKEN" in step
        assert "github.token" not in step

    assert "refusing any GITHUB_TOKEN fallback" in live_publish
    assert "refusing any GITHUB_TOKEN or author fallback" in publish


def test_publication_authority_refresh_precedes_private_sibling_live_revalidation() -> None:
    """Fresh scoped App/OIDC authority must exist before the private live-PR lookup."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    app_marker = "      - name: Refresh repository-scoped Noema GitHub App token for publication\n"
    oidc_marker = "      - name: Refresh repository-scoped Noema OIDC app token for publication\n"
    live_marker = "      - name: Revalidate live Noema target before publication\n"
    publish_marker = "      - name: Publish prepared Noema verdict on the exact live head\n"

    assert workflow.index(app_marker) < workflow.index(live_marker)
    assert workflow.index(oidc_marker) < workflow.index(live_marker)
    assert workflow.index(live_marker) < workflow.index(publish_marker)


def test_prepare_and_publish_are_the_only_model_verdict_execution_path() -> None:
    """The old single-process review path must not survive beside the handoff."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Run Noema LLM review and submit verdict" not in workflow
    assert "python3 -m scripts.ci.noema_review_gate" not in workflow
    assert workflow.count("--prepare-verdict-file") == 1
    assert workflow.count("--publish-verdict-file") == 1
