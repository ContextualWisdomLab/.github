"""Contracts for rerun-safe OpenCode coverage artifact handoff."""

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/opencode-review-dispatch.yml")
TEMPORARY_REPAIR_PATHS = (
    Path(".github/opencode-attempt-scoped-coverage-artifact.trigger"),
    Path(".github/workflows/materialize-opencode-attempt-scoped-coverage-artifact.yml"),
    Path(".github/workflows/opencode-coverage-artifact-rerun-repair.yml"),
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

    assert (
        "artifact-ids: "
        "${{ needs.coverage-source-tree.outputs.coverage_source_artifact_id }}"
        in evidence_job
    )
    assert "name: opencode-coverage-source\n" not in evidence_job


def test_missing_current_attempt_artifact_fails_with_fresh_run_guidance() -> None:
    """Reject partial reruns instead of falling back to stale source evidence."""
    workflow = _workflow_text()
    evidence_job = _job_block(workflow, "coverage-evidence", "opencode-review-target")

    assert "id: coverage_source_download" in evidence_job
    assert "continue-on-error: true" in evidence_job
    assert (
        "if: steps.coverage_source_download.outcome != 'success'" in evidence_job
    )
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
