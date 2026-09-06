"""Contracts removing hand-selected Strix severity thresholds from merge decisions."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
GATE = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"


def test_required_strix_workflow_has_no_hand_selected_severity_threshold() -> None:
    """A current vulnerability artifact is evidence; CI must not invent a cutoff."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "STRIX_FAIL_ON_MIN_SEVERITY" not in workflow
    assert "at or above" not in workflow
    assert "below-threshold" not in workflow


def test_successful_strix_execution_fails_closed_on_any_current_vulnerability_artifact() -> None:
    """The reusable gate must not convert severity labels to an admission score."""
    gate = GATE.read_text(encoding="utf-8")
    assert (
        "Current Strix vulnerability report exists; failing closed without a repository-authored severity threshold."
        in gate
    )
    assert "Strix exited successfully but emitted a vulnerability at or above" not in gate
