"""Regression checks for the central product and technical gap baseline."""

import re
from pathlib import Path


BASELINE = Path("docs/product-technical-gap-baseline.md")
ADR = Path("docs/adr/0002-product-technical-gap-baseline.md")
DOCTORING = Path("docs/doctoring/product-technical-gap-baseline.md")


def test_baseline_binds_current_governance_sources_and_buyer_contract() -> None:
    """The shipped baseline must point agents to product, governance, and evidence."""
    source = BASELINE.read_text(encoding="utf-8")

    for marker in (
        "CWL Master Context",
        "naruon #974",
        "GitHub Project #1",
        "PRD acceptance",
        "TRD target",
        "UML-level dependency",
        "Gap register",
        "Figma File ID",
        "APA 7th references",
        "G-01",
        "G-14",
        "exact HEAD",
        "independent current-head approval",
        "COPILOT_GITHUB_TOKEN",
        "Same-session open/close delta",
        "merge authorization",
        "병합 판단에는 재사용하지 않는다",
    ):
        assert marker in source, marker


def test_baseline_inventory_contains_sha_bound_open_pr_rows() -> None:
    """The captured inventory must include SHA and merge metadata for every row.

    This is snapshot completeness, not merge authorization. The test does not
    freeze specific SHAs and does not treat CLEAN/MERGEABLE as approval.
    """
    source = BASELINE.read_text(encoding="utf-8")
    rows = [line for line in source.splitlines() if line.startswith("| #")]

    declared_count = int(
        re.search(r"현재 열린 PR 수:\s*\*\*(\d+)\*\*", source).group(1)
    )
    assert declared_count > 0
    assert len(rows) == declared_count
    allowed_merge_states = {
        "MERGEABLE",
        "CONFLICTING",
        "BLOCKED",
        "BEHIND",
        "DIRTY",
        "UNSTABLE",
        "CLEAN",
    }
    for row in rows:
        assert re.search(r"\| #[0-9]+ \|", row), row
        assert re.search(r"[0-9a-f]{40}", row), row
        assert any(state in row for state in allowed_merge_states), row
        assert "merge authorization" not in row.lower()


def test_baseline_records_the_ui_adr_boundary() -> None:
    """The ADR states why a central UI file is not applicable."""
    adr = ADR.read_text(encoding="utf-8")
    doctoring = DOCTORING.read_text(encoding="utf-8")
    assert "Figma File ID: N/A" in adr
    assert "Storybook" in adr
    assert "Figma File ID" in doctoring
    assert "APA 7th" in doctoring
    assert "ISO/IEC 27001:2022" in doctoring
