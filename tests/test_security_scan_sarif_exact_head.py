"""Durable exact-head SARIF contracts for central repository scanners."""

from pathlib import Path


WORKFLOW_PATH = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "security-scan.yml"
)


def _job_block(workflow: str, job_name: str) -> str:
    """Return one two-space-indented GitHub Actions job block."""

    normalized = workflow.replace("\r\n", "\n").replace("\r", "\n")
    marker = f"\n  {job_name}:\n"
    start = normalized.index(marker) + len(marker)
    remaining = normalized[start:]
    offset = 0
    for line in remaining.splitlines(keepends=True):
        if offset and line.startswith("  ") and not line.startswith("    "):
            if line.rstrip().endswith(":"):
                return remaining[:offset]
        offset += len(line)
    return remaining


def test_repository_scanner_sarif_is_attributed_to_the_literal_head() -> None:
    """Trivy and Scorecard SARIF must identify the exact scanned head SHA."""

    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    expected_ref = "ref: refs/pull/${{ github.event.pull_request.number }}/head"
    expected_sha = "sha: ${{ github.event.pull_request.head.sha }}"

    for job_name in ("trivy-fs", "scorecard"):
        job = _job_block(workflow, job_name)
        assert expected_ref in job
        assert expected_sha in job
