"""Exact-head contracts for the organization security scanner workflow."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "security-scan.yml"


def workflow_job(workflow: str, job_name: str) -> str:
    """Return one top-level job block from the central security workflow.

    The workflow uses two-space-indented job identifiers. Normalizing line
    endings keeps this contract deterministic on Windows and Unix checkouts.
    """

    normalized = workflow.replace("\r\n", "\n").replace("\r", "\n")
    marker = f"\n  {job_name}:\n"
    start = normalized.index(marker) + len(marker)
    remaining = normalized[start:]
    candidates = [
        offset
        for line in remaining.splitlines(keepends=True)
        if (offset := remaining.find(line)) >= 0
        and line.startswith("  ")
        and not line.startswith("    ")
        and line.rstrip().endswith(":")
    ]
    if not candidates:
        return remaining
    first = min(offset for offset in candidates if offset > 0)
    return remaining[:first]


def test_repository_scanners_checkout_the_literal_pull_request_head() -> None:
    """Trivy and Scorecard must never scan GitHub's synthetic merge ref."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    exact_repository = "repository: ${{ github.event.pull_request.head.repo.full_name }}"
    exact_head = "ref: ${{ github.event.pull_request.head.sha }}"

    for job_name in ("trivy-fs", "scorecard"):
        job = workflow_job(workflow, job_name)
        assert exact_repository in job
        assert exact_head in job
        assert "persist-credentials: false" in job


def test_dependency_review_checkout_is_bound_to_the_same_exact_head() -> None:
    """Supporting checkout evidence must match the API comparison head."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    job = workflow_job(workflow, "dependency-review")

    assert "repository: ${{ github.event.pull_request.head.repo.full_name }}" in job
    assert "ref: ${{ github.event.pull_request.head.sha }}" in job
    assert "HEAD_SHA: ${{ github.event.pull_request.head.sha }}" in job
