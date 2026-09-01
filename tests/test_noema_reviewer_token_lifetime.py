"""Regression contract for Noema reviewer credential lifetime.

The repository-scoped cwl-noema-review GitHub App token is intentionally
short-lived. A long contextual-orchestrator review can outlive the token
minted before model work, so the trusted workflow must separate model
preparation from publication and mint a fresh least-privilege App token after
model work, before any reviewer-authorized publication operation.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "noema-review.yml"
APP_TOKEN_ACTION = (
    "uses: actions/create-github-app-token@"
    "bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3.2.0"
)


def _positions(text: str, needle: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while True:
        position = text.find(needle, start)
        if position < 0:
            return positions
        positions.append(position)
        start = position + len(needle)


def test_noema_remints_repository_scoped_app_token_after_model_before_publication() -> None:
    """A long model call must not publish with its predecessor App token."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    token_actions = _positions(workflow, APP_TOKEN_ACTION)

    # The first token admits the review and supplies the independent reviewer
    # identity. A second action-backed mint is required after model work so a
    # one-hour installation credential cannot expire before publication.
    assert len(token_actions) >= 2, (
        "Noema must mint a fresh repository-scoped GitHub App token after "
        "model work instead of reusing the pre-model installation token"
    )

    prepare = workflow.index("--prepare-verdict-file")
    publish = workflow.index("--publish-verdict-file")
    assert token_actions[0] < prepare < token_actions[-1] < publish

    # Both phases stay bound to the exact same target/head, and the model
    # route remains contextual-orchestrator's free pool rather than a direct
    # provider escape hatch.
    assert workflow.count('--expected-head "$EXPECTED_HEAD_SHA"') >= 2
    assert 'export NOEMA_LLM_MODEL="orchestrator/free"' in workflow


def test_noema_publication_refresh_keeps_least_privilege_repository_scope() -> None:
    """Refreshing the reviewer must not broaden identity or permissions."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    token_actions = _positions(workflow, APP_TOKEN_ACTION)
    assert len(token_actions) >= 2

    publication_mint = workflow[token_actions[-1] :]
    assert "owner: ContextualWisdomLab" in publication_mint
    assert "repositories: ${{ steps.noema_credential.outputs.repository }}" in publication_mint
    assert "permission-pull-requests: write" in publication_mint
    assert "permission-contents: read" in publication_mint
    assert "permission-actions: read" in publication_mint
    assert "NOEMA_REVIEW_TOKEN" not in publication_mint.split("--publish-verdict-file", 1)[0]
