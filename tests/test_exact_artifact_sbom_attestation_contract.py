"""Contracts for the organization-owned exact-artifact SBOM attestation workflow."""

from __future__ import annotations

import re
from pathlib import Path

REUSABLE_WORKFLOW = Path(
    ".github/workflows/exact-artifact-sbom-attestation.yml"
)
VERIFIER = Path("scripts/ci/verify_exact_artifact_sbom_handoff.py")
DOCTORING = Path("docs/doctoring/exact-artifact-sbom-attestation.md")
ATTEST_ACTION_PIN = "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26"
CHECKOUT_ACTION_PIN = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"


def _required_text(path: Path, label: str) -> str:
    """Return one required UTF-8 repository file or fail with a useful contract."""
    assert path.is_file(), f"{label} is missing: {path}"
    return path.read_text(encoding="utf-8")


def _workflow_call_block(workflow: str) -> str:
    """Return the top-level event block from one GitHub Actions workflow."""
    match = re.search(r"(?ms)^on:\n(?P<body>.*?)(?=^\S|\Z)", workflow)
    assert match is not None, "workflow must declare a top-level on block"
    return match.group("body")


def test_reusable_workflow_is_call_only_with_explicit_handoff_inputs() -> None:
    """Accept sealed evidence only through an explicit reusable-workflow contract."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")
    event_block = _workflow_call_block(workflow)

    assert re.search(r"(?m)^  workflow_call:\s*$", event_block)
    for forbidden_trigger in (
        "pull_request",
        "push",
        "schedule",
        "workflow_dispatch",
        "repository_dispatch",
    ):
        assert not re.search(
            rf"(?m)^  {re.escape(forbidden_trigger)}:\s*$",
            event_block,
        )

    required_inputs = {
        "source_repository",
        "source_sha",
        "evidence_artifact_name",
        "evidence_artifact_digest",
        "wheel_filename",
        "wheel_sha256",
        "wheel_sbom_filename",
        "wheel_sbom_sha256",
        "sdist_filename",
        "sdist_sha256",
        "sdist_sbom_filename",
        "sdist_sbom_sha256",
        "source_identity_sha256",
        "checksum_sha256",
        "predicate_type",
        "cyclonedx_schema",
    }
    for input_name in required_inputs:
        input_match = re.search(
            rf"(?ms)^      {re.escape(input_name)}:\n"
            rf"(?P<body>(?:^        .*\n)+)",
            event_block,
        )
        assert input_match is not None, f"missing workflow input: {input_name}"
        input_body = input_match.group("body")
        assert re.search(r"(?m)^        required: true\s*$", input_body)
        assert re.search(r"(?m)^        type: string\s*$", input_body)


def test_credentialed_job_uses_exact_permissions_and_immutable_trusted_source() -> None:
    """Keep signing authority separate from caller-controlled source and credentials."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")

    assert ATTEST_ACTION_PIN in workflow
    assert CHECKOUT_ACTION_PIN in workflow
    assert "repository: ${{ job.workflow_repository }}" in workflow
    assert "ref: ${{ job.workflow_sha }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "id-token: write" in workflow
    assert "attestations: write" in workflow
    assert "artifact-metadata: write" in workflow
    assert "contents: read" in workflow

    for forbidden_permission in (
        "actions: write",
        "contents: write",
        "issues: write",
        "packages: write",
        "pull-requests: write",
        "security-events: write",
    ):
        assert forbidden_permission not in workflow

    assert "actions/checkout@" in workflow
    assert "repository: ${{ github.repository }}" not in workflow
    assert "ref: ${{ inputs.source_sha }}" not in workflow
    assert "secrets: inherit" not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "NVIDIA_NIM_API_KEY" not in workflow


def test_verifier_is_data_only_and_workflow_never_executes_downloaded_evidence() -> None:
    """Treat every caller artifact as inert bounded data before attestation."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")
    verifier = _required_text(VERIFIER, "sealed-evidence verifier")

    assert "verify_exact_artifact_sbom_handoff.py" in workflow
    assert "--source-repository" in workflow
    assert "--source-sha" in workflow
    assert "--evidence-root" in workflow
    assert "--output-manifest" in workflow
    assert "subprocess" not in verifier
    assert "os.system" not in verifier
    assert "exec(" not in verifier
    assert "eval(" not in verifier
    assert "importlib" not in verifier
    assert "zipfile" not in verifier
    assert "tarfile" not in verifier

    for unsafe_command in (
        "pip install",
        "python -m build",
        "pytest",
        "npm ",
        "cargo ",
        "chmod +x",
        "source ",
    ):
        assert unsafe_command not in workflow


def test_workflow_attests_each_exact_distribution_and_exports_offline_evidence() -> None:
    """Bind one CycloneDX predicate to each exact distribution and preserve bundles."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")

    assert workflow.count(ATTEST_ACTION_PIN) == 2
    assert workflow.count("sbom-path:") == 2
    assert workflow.count("subject-name:") == 2
    assert workflow.count("subject-digest:") == 2
    assert "predicate-type" in workflow
    assert "bundle-path" in workflow
    assert "gh attestation verify" in workflow
    assert "--signer-repo" in workflow
    assert "--signer-workflow" in workflow
    assert "--predicate-type" in workflow
    assert "offline" in workflow.lower()


def test_doctoring_records_claim_boundary_recovery_and_primary_sources() -> None:
    """Require buyer-readable operations, rollback, nonclaims, and APA 7 evidence."""
    doctoring = _required_text(DOCTORING, "SBOM attestation doctoring")

    for required_section in (
        "## Trust boundary",
        "## Exact-head lifecycle",
        "## Offline verification",
        "## Incident recovery and rollback",
        "## Claims deliberately not made",
        "## References",
    ):
        assert required_section in doctoring

    assert "SLSA Build Lx (v1.2)" in doctoring
    assert "59d89421af93a897026c735860bf21b6eb4f7b26" in doctoring
    assert "CycloneDX specification 1.7" in doctoring
    assert "SLSA specification version 1.2" in doctoring
    assert "Using artifact attestations" in doctoring
