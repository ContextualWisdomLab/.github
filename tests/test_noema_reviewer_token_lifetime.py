"""Regression contract for Noema reviewer credential lifetime."""

from pathlib import Path

import pytest


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
    next_job = text.find("\n  continue-noema-transport:\n", start + len(marker))
    ends = [end for end in (next_step, next_job) if end >= 0]
    return text[start:min(ends)] if ends else text[start:]


def test_noema_remints_repository_scoped_app_token_after_model_before_publication() -> None:
    """A long model call must not publish with its predecessor App token."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    prepare = _step_block(workflow, "Prepare Noema model verdict")
    refresh = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert APP_TOKEN_ACTION in refresh
    assert "--prepare-production" in prepare
    assert "--publish-production" in publish
    assert 'scripts/ci/premerge_review_tooling.py' in prepare
    assert 'scripts/ci/premerge_review_tooling.py' in publish
    assert '--verdict-file "$verdict_file"' in prepare
    assert '--verdict-file "$verdict_file"' in publish
    assert workflow.index(prepare) < workflow.index(refresh) < workflow.index(publish)
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in prepare
    assert '--expected-head "$EXPECTED_HEAD_SHA"' in publish
    assert 'export NOEMA_LLM_MODEL="orchestrator/auto"' in prepare
    assert "steps.noema_prepare.outputs.prepared == 'true'" in refresh
    assert "steps.noema_credential.outputs.source == 'github-app'" in refresh
    assert "steps.noema_prepare.outputs.prepared == 'true'" in publish


def test_publication_step_uses_fresh_app_token_without_authority_fallback() -> None:
    """Publication selects the refreshed App token and fails closed for unknown sources."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    refresh = _step_block(workflow, "Refresh repository-scoped Noema GitHub App token for publication")
    publish = _step_block(workflow, "Publish prepared Noema verdict on the exact live head")

    assert "owner: ContextualWisdomLab" in refresh
    assert "repositories: ${{ steps.noema_credential.outputs.repository }}" in refresh
    assert "permission-pull-requests: write" in refresh
    assert "permission-contents: read" in refresh
    assert "permission-actions: read" in refresh
    assert "steps.noema_github_app_publication_token.outputs.token" in publish
    assert "steps.noema_github_app_token.outputs.token" not in publish
    assert "secrets.NOEMA_REVIEW_TOKEN" in publish
    assert "steps.noema_oidc_token.outputs.token" in publish
    assert "github.token" not in publish
    assert "refusing any GITHUB_TOKEN or author fallback" in publish


def test_prepare_and_publish_are_the_only_model_verdict_execution_path() -> None:
    """The old single-process review path must not survive beside the handoff."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "Run Noema LLM review and submit verdict" not in workflow
    assert "python3 -m scripts.ci.noema_review_gate" not in workflow
    assert workflow.count("--prepare-production") == 1
    assert workflow.count("--publish-production") == 1
    assert workflow.count("--phase-issuance") == 2
    assert '--prepare-verdict-file' not in workflow
    assert '--publish-verdict-file' not in workflow


@pytest.mark.parametrize("old_flag", ["--prepare-verdict-file", "--publish-verdict-file"])
def test_phase_contract_rejects_obsolete_flags_with_current_path_retained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, old_flag: str,
) -> None:
    """An extra obsolete flag must be rejected even beside valid phase calls."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    mutated = tmp_path / "noema-review.yml"
    current_flag = "--prepare-production" if old_flag == "--prepare-verdict-file" else "--publish-production"
    assert workflow.count(current_flag) == 1
    mutated.write_text(
        workflow.replace(current_flag, f"{current_flag} {old_flag}"), encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "WORKFLOW", mutated)
    with pytest.raises(AssertionError):
        test_prepare_and_publish_are_the_only_model_verdict_execution_path()
