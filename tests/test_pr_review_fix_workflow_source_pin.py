"""Contract tests for immutable review-fix scheduler source selection."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github/workflows/pr-review-fix-scheduler.yml"


def workflow_text() -> str:
    """Return the central review-fix workflow as reviewed source text."""
    return WORKFLOW.read_text(encoding="utf-8")


def test_review_fix_runtime_is_bound_to_called_workflow_sha() -> None:
    """Prevent a source-pinned caller from drifting to mutable central main."""
    workflow = workflow_text()

    assert "Resolve trusted scheduler source ref" in workflow
    assert "JOB_CONTEXT_JSON: ${{ toJSON(job) }}" in workflow
    assert "GITHUB_CONTEXT_JSON: ${{ toJSON(github) }}" in workflow
    assert 'job_context.get("workflow_sha")' in workflow
    assert 're.fullmatch(r"[0-9a-fA-F]{40}", trusted_ref)' in workflow
    assert "ref: ${{ steps.trusted_source.outputs.ref }}" in workflow
    assert "CANONICAL_REF: main" not in workflow
    assert "ref: ${{ env.CANONICAL_REF }}" not in workflow


def test_optional_caller_expectation_must_match_immutable_sha() -> None:
    """Keep canonical_ref as an equality assertion rather than a source selector."""
    workflow = workflow_text()

    assert "Optional expected immutable SHA for the called scheduler workflow" in workflow
    assert "CANONICAL_REF_INPUT:" in workflow
    assert "expected_ref.lower() != trusted_ref.lower()" in workflow
    assert (
        "Caller canonical_ref does not match the immutable called workflow SHA."
        in workflow
    )
