"""Supply-chain contract for the PR auto-rebase scheduler source checkout."""

from __future__ import annotations

from pathlib import Path


_WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "pr-auto-rebase.yml"
)


def _workflow_text() -> str:
    """Read the auto-rebase workflow as UTF-8 text."""
    return _WORKFLOW.read_text(encoding="utf-8")


def test_auto_rebase_validates_called_workflow_sha_before_checkout() -> None:
    """A floating branch tip must not be checked out before SHA validation."""
    workflow = _workflow_text()
    guard = workflow.index("Resolve immutable called-workflow source")
    checkout = workflow.index("Checkout immutable called-workflow source")

    assert guard < checkout
    assert "CALLER_REPOSITORY: ${{ github.repository }}" in workflow
    assert "WORKFLOW_SHA: ${{ github.workflow_sha }}" in workflow
    assert '[ "$CALLER_REPOSITORY" != "$expected_repository" ]' in workflow
    assert 'expected_repository="ContextualWisdomLab/.github"' in workflow
    assert 'expected_file=".github/workflows/pr-auto-rebase.yml"' in workflow
    assert '[[ "$WORKFLOW_SHA" =~ ^[0-9a-f]{40}$ ]]' in workflow
    assert "repository: ${{ steps.trusted_source.outputs.repository }}" in workflow
    assert "ref: ${{ steps.trusted_source.outputs.sha }}" in workflow
    assert "ref: main" not in workflow
    assert "CANONICAL_REF: main" not in workflow
    assert "ref: ${{ env.CANONICAL_REF }}" not in workflow
    assert "ref: ${{ github.sha }}" not in workflow


def test_auto_rebase_verifies_checked_out_sha_matches_runtime_parameter() -> None:
    """The commit that executes must equal the validated 40-character SHA."""
    workflow = _workflow_text()
    verification = workflow.index("Verify immutable called-workflow checkout")
    self_test = workflow.index("Self-test auto-rebase scheduler contract")

    assert verification < self_test
    assert 'actual_sha="$(git rev-parse HEAD)"' in workflow
    assert '[ "$actual_sha" != "$EXPECTED_SHA" ]' in workflow
    assert '[ ! -f "$EXPECTED_FILE" ] || [ -L "$EXPECTED_FILE" ]' in workflow


def test_auto_rebase_canonical_ref_input_cannot_select_source() -> None:
    """Callers may still send canonical_ref, but it never selects the checkout."""
    workflow = _workflow_text()
    declaration = workflow.split("canonical_ref:", 1)[1].split(
        "repository_dispatch:", 1
    )[0]

    assert "Deprecated compatibility input" in declaration
    assert "ignored" in declaration
    assert 'default: ""' in declaration
    assert workflow.count("canonical_ref") == 1
    assert "inputs.canonical_ref" not in workflow
    assert "github.event.client_payload.canonical_ref" not in workflow
