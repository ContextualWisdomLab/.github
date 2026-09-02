"""Regression contracts for close-event runner admission pressure."""

from pathlib import Path


WORKFLOW = Path(__file__).parents[1] / ".github/workflows/close-empty-pr.yml"


def test_closed_pull_request_does_not_allocate_a_noop_runner() -> None:
    """Workflow concurrency can retire prior runs without a close-event job."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "types: [opened, synchronize, reopened, ready_for_review, closed]" in workflow
    assert "cancel-in-progress: true" in workflow
    assert "cancel-closed-pr-runs:" not in workflow
    assert "if: github.event.action != 'closed'" in workflow
