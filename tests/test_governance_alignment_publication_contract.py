"""Keep public governance evidence locators private and research claims bounded."""

from pathlib import Path
import re

import pytest


PUBLIC_DOCUMENTS = (
    Path("docs/governance-operating-alignment.md"),
    Path("docs/doctoring/governance-operating-alignment.md"),
)
DOCTORING = PUBLIC_DOCUMENTS[1]


@pytest.mark.parametrize("document", PUBLIC_DOCUMENTS)
def test_public_governance_documents_use_nonidentifying_evidence_locators(
    document: Path,
) -> None:
    """A public evidence pointer must not disclose a local user's home path."""
    source = document.read_text(encoding="utf-8")
    assert not re.search(r"/(?:Users|home)/[^/\s`]+|[A-Za-z]:\\Users\\", source)
    assert "access-controlled locator" in source


@pytest.mark.parametrize(
    "private_path",
    (
        "/home/alice",
        "/Users/alice",
        "`/home/alice`",
        "`/Users/alice`",
        "/home/alice/evidence",
        "/Users/alice/evidence",
        r"C:\Users\alice",
        r"C:\Users\alice\evidence",
    ),
)
def test_public_locator_guard_rejects_bare_and_nested_home_paths(
    tmp_path: Path,
    private_path: str,
) -> None:
    """Exercise the actual document guard with private home-root counterexamples."""
    document = tmp_path / "governance.md"
    document.write_text(
        f"Evidence (access-controlled locator): {private_path}\n", encoding="utf-8"
    )
    with pytest.raises(AssertionError):
        test_public_governance_documents_use_nonidentifying_evidence_locators(document)


def test_public_locator_guard_accepts_nonidentifying_locator(tmp_path: Path) -> None:
    """A valid public locator stays admissible through the same document guard."""
    document = tmp_path / "governance.md"
    document.write_text(
        "Evidence (access-controlled locator): governance-alignment-evidence.\n",
        encoding="utf-8",
    )
    test_public_governance_documents_use_nonidentifying_evidence_locators(document)


def test_doctoring_maps_retrieved_standards_without_claiming_certification() -> None:
    """Record applicable standards, their retrieval date and evidence limits."""
    source = " ".join(DOCTORING.read_text(encoding="utf-8").split())
    for marker in (
        "APA 7th",
        "2026-10-05",
        "ISO/IEC 27001:2022",
        "ISO/IEC 27001:2022/Amd 1:2024",
        "NIST SP 800-204D",
        "https://www.iso.org/standard/27001",
        "https://www.iso.org/standard/88435.html",
        "https://csrc.nist.gov/pubs/sp/800/204/d/final",
        "not certification",
        "full ISO text was not reviewed",
    ):
        assert marker in source, marker


def test_doctoring_records_paper_and_distinct_execution_acceptance() -> None:
    """A research citation must not stand in for installed provenance or CI."""
    source = " ".join(DOCTORING.read_text(encoding="utf-8").split())
    for marker in (
        "Torres-Arias",
        "(2019)",
        "in-toto",
        "1393–1410",
        "https://www.usenix.org/conference/usenixsecurity19/presentation/torres-arias",
        "not an in-toto deployment",
        "not runner registration",
        "not a qualifying GitHub approval",
    ):
        assert marker in source, marker
