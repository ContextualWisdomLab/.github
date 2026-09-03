"""Regression contract for the exact-artifact outer transport receipt."""

from pathlib import Path

from scripts.ci import verify_exact_artifact_sbom_handoff as verifier


_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOW = _REPOSITORY_ROOT / ".github/workflows/exact-artifact-sbom-attestation.yml"


def test_source_identity_is_constructible_before_github_returns_artifact_digest() -> None:
    """Keep the post-upload GitHub digest out of the pre-upload inner identity."""
    source = Path(verifier.__file__).read_text(encoding="utf-8")

    assert '"evidence_artifact_digest": arguments.evidence_artifact_digest' not in source
    assert 'parser.add_argument("--evidence-artifact-digest"' not in source


def test_outer_artifact_receipt_is_reverified_before_credentialed_signing() -> None:
    """Verify the returned artifact receipt twice without moving it into inner bytes."""
    workflow = _WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("Verify immutable same-run artifact metadata") == 2
    assert workflow.count(".digest == $digest") == 2
    assert workflow.count(".workflow_run.id == $run_id") == 2
    assert workflow.count("--evidence-artifact-digest") == 0
    assert "evidence_artifact_digest:" in workflow
