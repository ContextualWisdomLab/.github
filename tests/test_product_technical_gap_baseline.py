"""Regression checks for the central product and technical gap baseline."""

import re
from pathlib import Path


BASELINE = Path("docs/product-technical-gap-baseline.md")


def test_baseline_binds_current_governance_sources_and_buyer_contract() -> None:
    """The baseline must point agents to live product and governance evidence."""
    source = BASELINE.read_text(encoding="utf-8")

    for marker in (
        "CWL Master Context",
        "naruon #974",
        "GitHub Project #1",
        "PRD acceptance",
        "TRD target",
        "UML-level dependency",
        "Figma File ID",
        "APA 7th references",
        "G-01",
        "G-14",
        "exact-head",
        "independent current-head approval",
        "COPILOT_GITHUB_TOKEN",
    ):
        assert marker in source


def test_baseline_inventory_contains_sha_bound_open_pr_rows() -> None:
    """The captured inventory must include a SHA and disposition for each row."""
    source = BASELINE.read_text(encoding="utf-8")
    rows = [line for line in source.splitlines() if line.startswith("| #")]

    assert len(rows) >= 90
    for row in rows:
        assert re.search(r"`[0-9a-f]{40}`", row), row
        assert any(state in row for state in ("BLOCKED", "BEHIND", "DIRTY")), row


def test_baseline_links_existing_local_evidence() -> None:
    """Every local evidence link in the baseline resolves from the docs folder."""
    for relative_path in (
        "CWL-MASTER-CONTEXT.md",
        "doctoring/organization-commercial-readiness-loop.md",
    ):
        assert (BASELINE.parent / relative_path).is_file(), relative_path
