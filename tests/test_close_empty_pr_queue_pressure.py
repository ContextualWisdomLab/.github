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
    """Workflow concurrency can retire prior runs without a close-event job."""
    workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")

    assert "types: [opened, synchronize, reopened, ready_for_review, closed]" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "cancel-closed-pr-runs:" not in workflow
    assert "if: github.event.action != 'closed'" in workflow
    assert evidence_job in workflow
