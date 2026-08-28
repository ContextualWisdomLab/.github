"""Contracts for the organization-owned exact-artifact SBOM attestation workflow."""

from __future__ import annotations

import re
from pathlib import Path

REUSABLE_WORKFLOW = Path(
    ".github/workflows/exact-artifact-sbom-attestation.yml"
)
QUALITY_WORKFLOW = Path(
    ".github/workflows/exact-artifact-sbom-attestation-quality.yml"
)
VERIFIER = Path("scripts/ci/verify_exact_artifact_sbom_handoff.py")
DOCTORING = Path("docs/doctoring/exact-artifact-sbom-attestation.md")
ATTEST_ACTION_PIN = "actions/attest@59d89421af93a897026c735860bf21b6eb4f7b26"
CHECKOUT_ACTION_PIN = "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0"
DOWNLOAD_ACTION_PIN = (
    "actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c"
)
UPLOAD_ACTION_PIN = (
    "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"
)


def _required_text(path: Path, label: str) -> str:
    """Return one required UTF-8 repository file or fail with a useful contract."""
    assert path.is_file(), f"{label} is missing: {path}"
    return path.read_text(encoding="utf-8")


def _workflow_call_block(workflow: str) -> str:
    """Return the top-level event block from one GitHub Actions workflow."""
    match = re.search(r"(?ms)^on:\n(?P<body>.*?)(?=^\S|\Z)", workflow)
    assert match is not None, "workflow must declare a top-level on block"
    return match.group("body")


def _job_block(workflow: str, job_name: str) -> str:
    """Return one exact top-level job body from a workflow source file."""
    jobs_match = re.search(r"(?ms)^jobs:\n(?P<body>.*)\Z", workflow)
    assert jobs_match is not None, "workflow must declare jobs"
    jobs_body = jobs_match.group("body")
    job_match = re.search(
        rf"(?ms)^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)",
        jobs_body,
    )
    assert job_match is not None, f"missing workflow job: {job_name}"
    return job_match.group(0)


def _run_blocks(workflow: str) -> list[str]:
    """Return every indentation-bounded multiline shell body."""
    lines = workflow.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index] != "        run: |":
            index += 1
            continue
        index += 1
        body: list[str] = []
        while index < len(lines) and (
            lines[index].startswith("          ") or lines[index] == ""
        ):
            body.append(lines[index])
            index += 1
        blocks.append("\n".join(body))
    return blocks


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
        "evidence_artifact_id",
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


def test_artifact_intake_verifies_exact_immutable_same_run_metadata() -> None:
    """Fail closed on artifact identity before the credentialed attestation job."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")
    intake = _job_block(workflow, "verify-evidence-artifact")

    assert "permissions:" in intake
    assert "actions: read" in intake
    assert "contents: read" in intake
    assert "id-token: write" not in intake
    assert "attestations: write" not in intake
    assert "artifact-metadata: write" not in intake
    assert "${{ inputs.evidence_artifact_id }}" in intake
    assert "${{ inputs.evidence_artifact_name }}" in intake
    assert "${{ inputs.evidence_artifact_digest }}" in intake
    assert "${{ inputs.source_repository }}" in intake
    assert "GITHUB_RUN_ID" in intake
    assert "/actions/artifacts/" in intake
    assert ".workflow_run.id" in intake
    assert ".expired" in intake
    assert DOWNLOAD_ACTION_PIN in intake
    assert "artifact-ids: ${{ inputs.evidence_artifact_id }}" in intake


def test_credentialed_job_uses_exact_permissions_and_immutable_trusted_source() -> None:
    """Keep signing authority separate from caller-controlled source and credentials."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")
    signer = _job_block(workflow, "attest-exact-artifacts")

    assert ATTEST_ACTION_PIN in signer
    assert CHECKOUT_ACTION_PIN in workflow
    # job.workflow_repository/workflow_sha are not real Actions context
    # properties (actionlint flags them as undefined on the `job` object) and
    # always resolved empty, silently defaulting checkout away from the
    # pinned trusted verifier source. ContextualWisdomLab/.github is this
    # workflow's own repository; github.workflow_sha is the real, documented
    # property for its pinned commit.
    assert workflow.count("repository: ContextualWisdomLab/.github") >= 2
    assert workflow.count("ref: ${{ github.workflow_sha }}") >= 2
    assert "${{ job.workflow_repository }}" not in workflow
    assert "${{ job.workflow_sha }}" not in workflow
    assert workflow.count("persist-credentials: false") >= 2
    assert "needs: verify-evidence-artifact" in signer
    assert "contents: read" in signer
    assert "id-token: write" in signer
    assert "attestations: write" in signer
    assert "artifact-metadata: write" in signer
    assert "actions: read" not in signer

    for forbidden_permission in (
        "actions: write",
        "contents: write",
        "issues: write",
        "packages: write",
        "pull-requests: write",
        "security-events: write",
    ):
        assert forbidden_permission not in workflow

    assert DOWNLOAD_ACTION_PIN in signer
    assert "artifact-ids: ${{ inputs.evidence_artifact_id }}" in signer
    assert "repository: ${{ github.repository }}" not in workflow
    assert "ref: ${{ inputs.source_sha }}" not in workflow
    assert "secrets: inherit" not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "NVIDIA_NIM_API_KEY" not in workflow


def test_verifier_is_data_only_and_workflow_never_executes_downloaded_evidence() -> None:
    """Treat every caller artifact as inert bounded data before attestation."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")
    verifier = _required_text(VERIFIER, "sealed-evidence verifier")

    assert workflow.count("verify_exact_artifact_sbom_handoff.py") >= 2
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

    run_blocks = _run_blocks(workflow)
    assert run_blocks, "workflow must declare multiline run blocks"
    for block in run_blocks:
        assert "${{ inputs." not in block, (
            "caller input must enter shell commands through an environment variable: "
            f"{block}"
        )

    for unsafe_command in (
        "pip install",
        "python -m build",
        "pytest",
        "npm ",
        "cargo ",
        "chmod +x",
        "source ",
    ):
        assert not re.search(
            rf"(?m)^\s*{re.escape(unsafe_command)}",
            workflow,
        )


def test_workflow_attests_each_exact_distribution_and_exports_offline_evidence() -> None:
    """Bind one CycloneDX predicate to each exact distribution and preserve bundles."""
    workflow = _required_text(REUSABLE_WORKFLOW, "reusable attestation workflow")
    signer = _job_block(workflow, "attest-exact-artifacts")

    assert signer.count(ATTEST_ACTION_PIN) == 2
    assert signer.count("sbom-path:") == 2
    assert signer.count("subject-name:") == 2
    assert signer.count("subject-digest:") == 2
    assert "predicate-type" in signer
    assert "bundle-path" in signer
    assert "gh attestation verify" in signer
    assert "--signer-repo" in signer
    assert "--signer-workflow" in signer
    assert "--predicate-type" in signer
    assert "gh attestation trusted-root" in signer
    assert UPLOAD_ACTION_PIN in signer
    assert "offline" in signer.lower()
    assert "offline-attestation-evidence/README.md" in signer
    assert "offline-attestation-evidence/SHA256SUMS" in signer
    assert "sha256sum" in signer


def test_quality_workflow_pins_supported_runner_images() -> None:
    """Keep exact supply-chain evidence on an explicit runner image."""
    workflow = _required_text(QUALITY_WORKFLOW, "attestation quality workflow")
    assert "ubuntu-latest" not in workflow
    assert workflow.count("runs-on: ubuntu-24.04") == 2


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

    assert "does not claim SLSA Build L3 (v1.2)" in doctoring
    assert "59d89421af93a897026c735860bf21b6eb4f7b26" in doctoring
    assert "CycloneDX specification 1.7" in doctoring
    assert "SLSA specification version 1.2" in doctoring
    assert "Using artifact attestations" in doctoring
