"""Contract tests for lineage-aware zero-diff pull-request cleanup."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "scripts" / "ci" / "pr_review_merge_scheduler_core.py"
PROCEDURE = ROOT / "docs" / "pr-review-and-merge-procedure.md"
BASELINE = ROOT / "docs" / "product-technical-gap-baseline.md"


def test_zero_diff_cleanup_requires_commit_lineage_and_fails_closed() -> None:
    """A base-to-head empty diff must not be the scheduler's sole close authority."""
    source = CORE.read_text(encoding="utf-8")

    assert "_fresh_commit_lineage_for_close" in source
    assert "incomplete commit lineage" in source
    assert "_zero_diff_close_authorized" in source
    assert '"wait"' in source[source.index("_zero_diff_close_authorized") :]


def test_governance_procedure_names_lineage_as_zero_diff_close_evidence() -> None:
    """Operator guidance must preserve the lineage guard against reverted work."""
    procedure = PROCEDURE.read_text(encoding="utf-8")

    assert "Zero-diff" in procedure
    assert "commit lineage" in procedure
    assert "fails\nclosed" in procedure


def test_product_gap_baseline_records_the_lineage_guard() -> None:
    """The product baseline must retain the incident and its bounded repair."""
    baseline = BASELINE.read_text(encoding="utf-8")

    assert "Item 42: zero-diff PR cleanup required commit-lineage evidence" in baseline
    assert "non-empty lineage returns a wait decision" in baseline
