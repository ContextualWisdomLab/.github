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
        "ContextualWisdomLab/naruon#974",
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

    declared = re.search(r"현재 열린 PR 수:\s*\*\*(\d+)\*\*", source)
    assert declared is not None, "baseline header must declare the open PR count"
    declared_count = int(declared.group(1))
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


def test_master_context_points_at_live_baseline_without_freezing_shas() -> None:
    """Section 10 must send agents to the live snapshot and UI-scope ADR.

    This pins narrative pointers, not inventory SHAs or merge authorization.
    """
    source = Path("docs/CWL-MASTER-CONTEXT.md").read_text(encoding="utf-8")
    assert "product-technical-gap-baseline.md" in source
    assert "Figma File ID" in source
    assert "N/A" in source
    assert "ContextualWisdomLab/naruon#974" in source
    assert "ContextualWisdomLab/naruon#975" in source
    assert "Done" in source
    assert "merge authorization" in source
