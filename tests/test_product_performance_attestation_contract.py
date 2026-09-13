"""Contracts for the organization-owned product performance attestation workflow."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/product-performance-attestation.yml")
VERIFIER = Path("scripts/ci/verify_product_performance_evidence.py")
ATTEST_ACTION_PIN = "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26"
DOWNLOAD_ACTION_PIN = (
    "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
)
UPLOAD_ACTION_PIN = (
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
)
PREDICATE_TYPE = "https://contextualwisdomlab.org/attestations/product-performance/v1"


def _text(path: Path) -> str:
    """Read one required UTF-8 repository file."""
    assert path.is_file(), f"required file is missing: {path}"
    return path.read_text(encoding="utf-8")


def test_reusable_workflow_has_explicit_performance_handoff_contract() -> None:
    """Require exact caller, artifact, evidence, profile, and predicate inputs."""
    workflow = _text(WORKFLOW)

    assert "workflow_call:" in workflow
    for name in (
        "source_repository",
        "source_sha",
        "evidence_artifact_id",
        "evidence_artifact_name",
        "evidence_artifact_digest",
        "result_filename",
        "result_sha256",
        "runtime_evidence_filename",
        "runtime_evidence_sha256",
        "fixture_filename",
        "fixture_sha256",
        "performance_profile",
        "predicate_type",
    ):
        assert f"      {name}:" in workflow
    assert PREDICATE_TYPE in workflow


def test_reusable_workflow_uses_oidc_callee_identity_before_trusted_checkout() -> None:
    """Keep caller workflow identity from selecting central verifier source."""
    workflow = _text(WORKFLOW)

    assert "ref: ${{ github.workflow_sha }}" not in workflow
    assert workflow.count("Resolve exact called reusable workflow identity") == 2
    assert workflow.count("job_workflow_ref") >= 2
    assert workflow.count("job_workflow_sha") >= 2
    assert workflow.count("id-token: write") >= 2
    assert workflow.count("ref: ${{ steps.workflow-identity.outputs.workflow_sha }}") >= 2
    assert workflow.count("product-performance-attestation.yml@") >= 2


def test_reusable_workflow_rechecks_same_run_artifact_and_never_executes_evidence() -> None:
    """Treat caller performance evidence as inert bounded data in both jobs."""
    workflow = _text(WORKFLOW)
    verifier = _text(VERIFIER)

    assert workflow.count("/actions/artifacts/${ARTIFACT_ID}") >= 2
    assert workflow.count(".workflow_run.id") >= 2
    assert workflow.count("artifact-ids: ${{ inputs.evidence_artifact_id }}") >= 2
    assert workflow.count(DOWNLOAD_ACTION_PIN) >= 2
    assert workflow.count("verify_product_performance_evidence.py") >= 2
    assert "subprocess" not in verifier
    assert "os.system" not in verifier
    assert "exec(" not in verifier
    assert "eval(" not in verifier
    assert "importlib" not in verifier
    assert "zipfile" not in verifier
    assert "tarfile" not in verifier


def test_signer_attests_result_with_versioned_custom_predicate_and_offline_bundle() -> None:
    """Bind exact result bytes to runtime and fixture evidence without claiming a latency verdict."""
    workflow = _text(WORKFLOW)

    assert workflow.count(ATTEST_ACTION_PIN) == 1
    assert "subject-name: ${{ inputs.result_filename }}" in workflow
    assert "subject-digest: sha256:${{ inputs.result_sha256 }}" in workflow
    assert "predicate-type: ${{ inputs.predicate_type }}" in workflow
    assert "predicate-path:" in workflow
    assert "gh attestation verify" in workflow
    assert "--signer-repo" in workflow
    assert "--signer-workflow" in workflow
    assert "--source-digest" in workflow
    assert "--predicate-type" in workflow
    assert "gh attestation trusted-root" in workflow
    assert UPLOAD_ACTION_PIN in workflow
    assert "does not prove" in workflow
