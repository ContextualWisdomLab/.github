"""Contracts for cross-repository reusable attestation workflow identity."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/exact-artifact-sbom-attestation.yml")
EXPECTED_WORKFLOW = (
    "ContextualWisdomLab/.github/.github/workflows/"
    "exact-artifact-sbom-attestation.yml@"
)
EXPECTED_ISSUER = "https://token.actions.githubusercontent.com"
EXPECTED_AUDIENCE = "https://github.com/ContextualWisdomLab/.github/reusable-workflow-source"


def test_reusable_attestation_resolves_its_own_exact_oidc_identity() -> None:
    """Reject caller workflow identity as a substitute for the called workflow SHA."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "ref: ${{ github.workflow_sha }}" not in workflow
    assert workflow.count("id-token: write") >= 2
    assert workflow.count("Resolve exact called reusable workflow identity") == 2
    assert workflow.count("ACTIONS_ID_TOKEN_REQUEST_URL") >= 2
    assert workflow.count("ACTIONS_ID_TOKEN_REQUEST_TOKEN") >= 2
    assert workflow.count("job_workflow_ref") >= 2
    assert workflow.count("job_workflow_sha") >= 2
    assert workflow.count(EXPECTED_WORKFLOW) >= 2
    assert workflow.count(EXPECTED_ISSUER) >= 2
    assert workflow.count(EXPECTED_AUDIENCE) >= 2
    assert workflow.count("ref: ${{ steps.workflow-identity.outputs.workflow_sha }}") >= 2


def test_oidc_identity_resolution_is_self_contained_and_fail_closed() -> None:
    """Resolve trusted source before checkout without executing caller-controlled code."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count("Authorization: Bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN}") >= 2
    assert workflow.count("curl --fail --silent --show-error --get") >= 2
    assert workflow.count("--data-urlencode \"audience=${OIDC_AUDIENCE}\"") >= 2
    assert workflow.count("runner_environment") >= 2
    assert workflow.count("github-hosted") >= 2
    assert workflow.count("full 40-hex") >= 2
    assert "ref: ${{ inputs.source_sha }}" not in workflow

    first_identity = workflow.index("Resolve exact called reusable workflow identity")
    first_checkout = workflow.index("Materialize immutable trusted verifier")
    assert first_identity < first_checkout
