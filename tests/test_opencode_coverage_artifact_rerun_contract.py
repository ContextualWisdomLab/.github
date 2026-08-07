"""Contracts for rerun-safe OpenCode coverage artifact handoff."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
TEMPORARY_REPAIR_PATHS = (
    Path(".github/opencode-attempt-scoped-coverage-artifact.trigger"),
    Path(".github/workflows/materialize-opencode-attempt-scoped-coverage-artifact.yml"),
    Path(".github/workflows/opencode-coverage-artifact-rerun-repair.yml"),
    Path(".github/workflows/pr812-finalize-attempt-artifact.yml"),
    Path("scripts/ci/prepare_opencode_attempt_artifact_patch.py"),
)


def _workflow_text() -> str:
    """Return the protected OpenCode repository-dispatch workflow source."""
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def _job_block(workflow: str, job_name: str, next_job_name: str) -> str:
    """Return one top-level workflow job block bounded by the next job."""
    start = workflow.index(f"  {job_name}:\n")
    end = workflow.index(f"\n  {next_job_name}:\n", start)
    return workflow[start:end]


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

    assert "id: coverage_source_identity" in evidence_job
    assert (
        "COVERAGE_SOURCE_ARTIFACT_ID: "
        "${{ needs.coverage-source-tree.outputs.coverage_source_artifact_id }}"
        in evidence_job
    )
    assert '[[ "$COVERAGE_SOURCE_ARTIFACT_ID" =~ ^[1-9][0-9]*$ ]]' in evidence_job
    assert "artifact_id=$COVERAGE_SOURCE_ARTIFACT_ID" in evidence_job
    assert (
        "if: steps.coverage_source_identity.outcome == 'success'" in evidence_job
    )
    assert (
        "artifact-ids: ${{ steps.coverage_source_identity.outputs.artifact_id }}"
        in evidence_job
    )
    assert (
        "artifact-ids: "
        "${{ needs.coverage-source-tree.outputs.coverage_source_artifact_id }}"
        not in evidence_job
    )
    assert "name: opencode-coverage-source\n" not in evidence_job


def test_coverage_source_requires_current_producer_attempt() -> None:
    """Reject reused producer output when a selective rerun advances the attempt."""
    workflow = _workflow_text()
    source_job = _job_block(workflow, "coverage-source-tree", "coverage-evidence")
    evidence_job = _job_block(workflow, "coverage-evidence", "opencode-review-target")

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
        in evidence_job
    )
    assert "CURRENT_RUN_ATTEMPT: ${{ github.run_attempt }}" in evidence_job
    assert '[ "$COVERAGE_SOURCE_RUN_ATTEMPT" != "$CURRENT_RUN_ATTEMPT" ]' in evidence_job
    assert "full rerun or a fresh repository dispatch" in evidence_job
    guard_index = evidence_job.index(
        "- name: Verify coverage source identity for current workflow attempt"
    )
    download_index = evidence_job.index(
        "- name: Download current-attempt materialized pull request merge tree"
    )
    assert guard_index < download_index


def test_missing_current_attempt_artifact_fails_with_fresh_run_guidance() -> None:
    """Reject partial reruns instead of falling back to stale source evidence."""
    workflow = _workflow_text()
    evidence_job = _job_block(workflow, "coverage-evidence", "opencode-review-target")

    assert "id: coverage_source_identity" in evidence_job
    assert "id: coverage_source_download" in evidence_job
    assert evidence_job.count("continue-on-error: true") >= 2
    assert "steps.coverage_source_identity.outcome != 'success'" in evidence_job
    assert "steps.coverage_source_download.outcome != 'success'" in evidence_job
    assert "failed-jobs-only rerun" in evidence_job
    assert "full rerun or a fresh repository dispatch" in evidence_job
    assert "GITHUB_RUN_ATTEMPT" in evidence_job
    assert "exit 1" in evidence_job


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
    """Keep transient materializers and repair branch writers out of the PR."""
    assert [str(path) for path in TEMPORARY_REPAIR_PATHS if path.exists()] == []
