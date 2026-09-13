"""Contracts for cross-repository reusable attestation workflow identity."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/exact-artifact-sbom-attestation.yml")
RESOLVER = Path("scripts/ci/resolve_reusable_workflow_identity.py")


def test_reusable_attestation_resolves_its_own_exact_oidc_identity() -> None:
    """Reject caller workflow identity as a substitute for the called workflow SHA."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ref: ${{ github.workflow_sha }}" not in workflow
    assert workflow.count("id-token: write") >= 2
    assert workflow.count("ACTIONS_ID_TOKEN_REQUEST_URL") >= 2
    assert workflow.count("ACTIONS_ID_TOKEN_REQUEST_TOKEN") >= 2
    assert workflow.count("job_workflow_ref") >= 2
    assert workflow.count("job_workflow_sha") >= 2
    assert workflow.count("resolve_reusable_workflow_identity.py") >= 2


def test_identity_resolver_requires_exact_central_workflow_and_full_sha() -> None:
    """Bind the trusted source checkout to one exact central reusable workflow revision."""
    resolver = RESOLVER.read_text(encoding="utf-8")

    assert "https://token.actions.githubusercontent.com" in resolver
    assert "ContextualWisdomLab/.github/.github/workflows/exact-artifact-sbom-attestation.yml@" in resolver
    assert "job_workflow_ref" in resolver
    assert "job_workflow_sha" in resolver
    assert "full 40-hex" in resolver
    assert "GITHUB_OUTPUT" in resolver
