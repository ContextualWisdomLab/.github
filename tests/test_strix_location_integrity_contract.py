"""Contract coverage for source-bound Strix finding locations."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
PROCEDURE = ROOT / "docs" / "pr-review-and-merge-procedure.md"
BASELINE = ROOT / "docs" / "product-technical-gap-baseline.md"


def test_gate_uses_one_source_bound_location_validator() -> None:
    """The shell gate must delegate range validation to the trusted helper."""
    source = GATE.read_text(encoding="utf-8")

    assert 'validate_strix_location_ranges.py' in source
    assert "retry_model_inconsistency" in source
    assert "mixed valid and out-of-range finding locations" in source


def test_governance_docs_record_source_bound_strix_evidence() -> None:
    """Procedure and baseline must describe the fail-closed location contract."""
    procedure = PROCEDURE.read_text(encoding="utf-8")
    baseline = BASELINE.read_text(encoding="utf-8")

    assert "Strix findings require source-tree location evidence" in procedure
    assert "Item 43: Strix finding locations must exist in the scanned tree" in baseline
