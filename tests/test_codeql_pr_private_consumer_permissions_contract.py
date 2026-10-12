"""Regression contract for CodeQL required-workflow private-consumer reads.

A private consumer failed at the first live-PR/status API reads because the
required workflow's job-scoped token omitted the fine-grained read grants those
REST endpoints require. Protected `.github/main` already carries the owner fix;
this contract keeps #2040's current-base reconciliation from dropping it while
preserving the branch's v2 dispatch and settlement work.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-pr.yml"


def _job_header(workflow: str, job_name: str, next_job_name: str | None = None) -> str:
    marker = f"  {job_name}:\n"
    assert marker in workflow
    block = workflow.split(marker, 1)[1]
    if next_job_name is not None:
        next_marker = f"  {next_job_name}:\n"
        assert next_marker in block
        block = block.split(next_marker, 1)[0]
    assert "    steps:\n" in block
    return block.split("    steps:\n", 1)[0]


def test_codeql_required_jobs_hold_private_consumer_read_grants() -> None:
    """Live PR and commit-status reads need explicit private-repository grants."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    analyze_header = _job_header(workflow, "analyze-head", "dispatch-current-head")
    dispatch_header = _job_header(workflow, "dispatch-current-head")

    for header in (analyze_header, dispatch_header):
        assert "      pull-requests: read\n" in header
        assert "      statuses: read\n" in header
        assert "      actions: write\n" not in header
