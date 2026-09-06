"""Contracts for rerun-safe OpenCode coverage artifact handoff."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
TEMPORARY_REPAIR_GLOBS = (
    ".github/opencode-attempt-scoped-coverage-artifact*.trigger",
    ".github/pr812*.trigger",
    ".github/workflows/*opencode*artifact*materializ*.yml",
    ".github/workflows/*opencode*artifact*repair*.yml",
    ".github/workflows/pr812-finalize*.yml",
    "scripts/ci/*opencode*artifact*patch*.py",
)


def _workflow_text() -> str:
    """Return the protected OpenCode repository-dispatch workflow source."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str, next_job_name: str) -> str:
    """Return one top-level workflow job block bounded by the next job."""
    start = workflow.index(f"  {job_name}:\n")
    end = workflow.index(f"\n  {next_job_name}:\n", start)
    return workflow[start:end]


def _step_block(job: str, step_name: str, next_step_name: str) -> str:
    """Return one workflow step bounded by the following named step."""
    start = job.index(f"      - name: {step_name}\n")
    end = job.index(f"\n      - name: {next_step_name}\n", start)
    return job[start:end]


def test_coverage_source_artifact_is_attempt_scoped_and_downloaded_by_id() -> None:
    """Bind every producer attempt to its immutable uploaded artifact ID."""
    workflow = _workflow_text()
    source_job = _job_block(workflow, "coverage-source-tree", "coverage-evidence")
    evidence_job = _job_block(workflow, "coverage-evidence", "opencode-review-target")

    assert (
        "coverage_source_artifact_id: "
        "${{ steps.coverage_source_upload.outputs.artifact-id }}"
        in source_job
    )
    assert "id: coverage_source_upload" in source_job
    assert "name: opencode-coverage-source-${{ github.run_attempt }}" in source_job
    assert "retention-days: 1" in source_job

    identity = _step_block(
        evidence_job,
        "Verify coverage source identity for current workflow attempt",
        "Download current-attempt materialized pull request merge tree",
    )
    download = _step_block(
        evidence_job,
        "Download current-attempt materialized pull request merge tree",
        "Report missing current-attempt coverage source",
    )
    assert "id: coverage_source_identity" in identity
    assert (
        "COVERAGE_SOURCE_ARTIFACT_ID: "
        "${{ needs.coverage-source-tree.outputs.coverage_source_artifact_id }}"
        in identity
    )
    assert '[[ "$COVERAGE_SOURCE_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]' in identity
    assert "artifact_id=$COVERAGE_SOURCE_ARTIFACT_ID" in identity
    assert (
        "artifact-ids: ${{ steps.coverage_source_identity.outputs.artifact_id }}"
        in download
    )
    assert (
        "artifact-ids: "
        "${{ needs.coverage-source-tree.outputs.coverage_source_artifact_id }}"
        not in download
    )
    assert "name: opencode-coverage-source\n" not in download


def test_coverage_source_requires_current_producer_attempt() -> None:
    """Reject reused producer output when a selective rerun advances the attempt."""
    workflow = _workflow_text()
    source_job = _job_block(workflow, "coverage-source-tree", "coverage-evidence")
    evidence_job = _job_block(workflow, "coverage-evidence", "opencode-review-target")
    identity = _step_block(
        evidence_job,
        "Verify coverage source identity for current workflow attempt",
        "Download current-attempt materialized pull request merge tree",
    )

    assert (
        "coverage_source_run_attempt: "
        "${{ steps.coverage_source_attempt.outputs.run_attempt }}"
        in source_job
    )
    assert "id: coverage_source_attempt" in source_job
    assert "GITHUB_RUN_ATTEMPT: ${{ github.run_attempt }}" in source_job
    assert "run_attempt=%s" in source_job

    assert (
        "COVERAGE_SOURCE_RUN_ATTEMPT: "
        "${{ needs.coverage-source-tree.outputs.coverage_source_run_attempt }}"
        in identity
    )
    assert "CURRENT_RUN_ATTEMPT: ${{ github.run_attempt }}" in identity
    assert '[ "$COVERAGE_SOURCE_RUN_ATTEMPT" != "$CURRENT_RUN_ATTEMPT" ]' in identity
    assert "failed-jobs-only reruns cannot reuse prior-attempt source evidence" in identity
    assert "full rerun or a fresh repository dispatch" in identity

    guard_index = evidence_job.index(
        "- name: Verify coverage source identity for current workflow attempt"
    )
    download_index = evidence_job.index(
        "- name: Download current-attempt materialized pull request merge tree"
    )
    assert guard_index < download_index


def test_missing_or_expired_artifact_fails_with_bounded_recovery_guidance() -> None:
    """Keep fail-closed recovery reachable after producer or download failures."""
    workflow = _workflow_text()
    evidence_job = _job_block(workflow, "coverage-evidence", "opencode-review-target")
    producer_failure = _step_block(
        evidence_job,
        "Report coverage source materialization failure",
        "Verify coverage source identity for current workflow attempt",
    )
    identity = _step_block(
        evidence_job,
        "Verify coverage source identity for current workflow attempt",
        "Download current-attempt materialized pull request merge tree",
    )
    download = _step_block(
        evidence_job,
        "Download current-attempt materialized pull request merge tree",
        "Report missing current-attempt coverage source",
    )
    recovery = _step_block(
        evidence_job,
        "Report missing current-attempt coverage source",
        "Prepare pull request merge tree for coverage measurement",
    )

    assert "if: needs.coverage-source-tree.result != 'success'" in producer_failure
    assert "exit 1" not in producer_failure
    assert "id: coverage_source_identity" in identity
    assert "if: always()" in identity
    assert "continue-on-error: true" in identity
    assert "id: coverage_source_download" in download
    assert "continue-on-error: true" in download
    assert "needs.coverage-source-tree.result == 'success'" in download
    assert "steps.coverage_source_identity.outcome == 'success'" in download
    assert "if: always() && (" in recovery
    assert "needs.coverage-source-tree.result != 'success'" in recovery
    assert "steps.coverage_source_identity.outcome != 'success'" in recovery
    assert "steps.coverage_source_download.outcome != 'success'" in recovery
    assert "failed-jobs-only rerun" in recovery
    assert "full rerun or a fresh repository dispatch" in recovery
    assert "GITHUB_RUN_ATTEMPT" in recovery
    assert "exit 1" in recovery
    assert "list-artifacts" not in identity + download + recovery


def test_coverage_consumer_remains_credential_free() -> None:
    """Keep repository and OIDC credentials outside the untrusted-test job."""
    workflow = _workflow_text()
    evidence_job = _job_block(workflow, "coverage-evidence", "opencode-review-target")
    permissions = evidence_job.split("    outputs:\n", 1)[0]

    assert "actions: read" in permissions
    assert "contents:" not in permissions
    assert "id-token:" not in permissions
    assert "secrets." not in evidence_job
    assert "GH_TOKEN:" not in evidence_job


def test_temporary_branch_writers_are_absent_from_final_tree() -> None:
    """Reject versioned or renamed materializers and branch finalizers."""
    unexpected = sorted(
        {
            str(path)
            for pattern in TEMPORARY_REPAIR_GLOBS
            for path in Path(".").glob(pattern)
        }
    )
    assert unexpected == []
