"""Contracts for the discoverable automation doctoring/reference authority."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTORING_INDEX = ROOT / "docs" / "doctoring" / "README.md"
STANDARDS = ROOT / "docs" / "doctoring" / "automation-control-plane-standards.md"
AUTOMATION_INDEX = ROOT / "docs" / "automation" / "README.md"


def test_doctoring_authority_is_indexed_from_canonical_automation_docs() -> None:
    """The canonical automation index links to one discoverable doctoring authority."""

    assert DOCTORING_INDEX.is_file()
    assert STANDARDS.is_file()
    doctoring = DOCTORING_INDEX.read_text(encoding="utf-8")
    automation = AUTOMATION_INDEX.read_text(encoding="utf-8")
    assert "automation-control-plane-standards.md" in doctoring
    assert "../doctoring/README.md" in automation
    assert "APA 7" in doctoring
    assert "candidate evidence" in doctoring


def test_doctoring_index_preserves_central_leaf_ownership_boundary() -> None:
    """Central reference authority does not silently absorb product specifications."""

    doctoring = DOCTORING_INDEX.read_text(encoding="utf-8")
    assert "shared automation control plane only" in doctoring
    for leaf_product in (
        "TEPP",
        "fast-mlsirm",
        "OriginWeave",
        "EmbedRelay",
        "MHTML ETL",
        "LifeOS",
        "BandScope",
        "Inkspan",
        "pg-erd-cloud",
        "naruon",
        "AppGuardrail",
    ):
        assert leaf_product in doctoring


def test_standards_reference_index_does_not_claim_certification() -> None:
    """Reference indexing cannot be mistaken for certification or formal assurance."""

    doctoring = DOCTORING_INDEX.read_text(encoding="utf-8")
    standards = STANDARDS.read_text(encoding="utf-8")
    assert "Never use citations to imply certification" in doctoring
    assert "does not establish certification" in standards
    assert "formal conformance" in standards
