"""Regression contracts for close-event runner admission pressure."""

from pathlib import Path

import pytest


WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"


@pytest.mark.parametrize(
    ("filename", "evidence_job"),
    (
        ("close-empty-pr.yml", "  close-empty:"),
        ("osv-scanner-pr.yml", "  osv-scan:"),
        ("scorecard-pr.yml", "  analysis:"),
    ),
)
def test_closed_pull_request_does_not_allocate_a_noop_runner(
    filename: str,
    evidence_job: str,
) -> None:
    """Workflow concurrency retires prior runs while the compatibility job skips."""
    workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")

    assert "types: [opened, synchronize, reopened, ready_for_review, closed]" in workflow
    assert "cancel-in-progress: true" in workflow
    sentinel = workflow.split("  cancel-closed-pr-runs:\n", 1)[1].split(
        f"\n{evidence_job}", 1
    )[0]
    assert "if: ${{ false }}" in sentinel
    assert "github.event.action == 'closed'" not in sentinel
    assert "PR closed; this run only cancels older runs through workflow concurrency." in sentinel
    assert "if: github.event.action != 'closed'" in workflow
    assert evidence_job in workflow