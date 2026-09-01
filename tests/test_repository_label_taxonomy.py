"""Contracts for the organization-wide repository label taxonomy."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "config" / "repository-label-taxonomy.json"
OPERATING_RECORDS = (
    ROOT / "docs" / "doctoring" / "repository-public-surface-reconciliation.md",
    ROOT / "docs" / "doctoring" / "repository-label-taxonomy-wave-3.md",
)
EXPECTED_ASSIGNMENTS = [
    (".github", 1579, "feature"),
    (".github", 1582, "feature"),
    (".github", 1622, "feature"),
    (".github", 1625, "bug"),
    (".github", 1634, "documentation"),
    ("CalendarWeave", 1, "documentation"),
    ("ConceptWeave", 1, "feature"),
    ("context-graph-contracts", 20, "documentation"),
    ("ThreadWeave", 37, "documentation"),
    ("RankWeave", 40, "documentation"),
    ("fast-mlsirm", 1717, "documentation"),
    ("fast-mlsirm", 1716, "documentation"),
    ("EgressWeave", 231, "documentation"),
    ("EgressWeave", 190, "documentation"),
    ("psychometrics-commons", 442, "documentation"),
    ("contextual-orchestrator", 994, "documentation"),
    ("contextual-orchestrator", 1003, "documentation"),
    ("appguardrail", 1077, "documentation"),
    ("naruon", 1513, "documentation"),
    ("LineageWeave", 908, "documentation"),
    ("ContextualWisdomLab.github.io", 203, "documentation"),
    ("TEPP", 435, "documentation"),
    ("semantic-data-portal", 72, "documentation"),
    ("Orgmetra", 160, "documentation"),
    ("learning-interoperability-contracts", 1, "feature"),
    ("noema", 530, "feature"),
    ("bandscope", 1125, "documentation"),
    ("saju-caldav", 44, "documentation"),
    ("saju-caldav", 42, "documentation"),
    ("OriginWeave", 274, "documentation"),
    ("semantic-data-portal", 90, "documentation"),
    ("accounting-information-platform", 45, "documentation"),
    ("clearfolio", 538, "documentation"),
    ("pg-erd-cloud", 1046, "documentation"),
    ("pg-erd-cloud", 1040, "documentation"),
    ("DiagramWeave", 34, "documentation"),
    ("DiagramWeave", 33, "documentation"),
    ("keyverse", 103, "feature"),
    ("mhtml-etl-gateway", 56, "documentation"),
    ("mhtml-etl-gateway", 44, "documentation"),
    ("j-planner", 2, "documentation"),
    ("learning-record-store", 1, "documentation"),
    ("learning-content-studio", 1, "documentation"),
    ("learning-management-platform", 1, "documentation"),
    ("metering-billing-platform", 157, "documentation"),
    ("PolicyWeave", 1, "feature"),
    ("supply-chain-control-plane", 1, "feature"),
    ("governance-risk-compliance", 65, "documentation"),
    ("pingora-gateway", 4, "documentation"),
    ("life-os", 211, "documentation"),
    ("scopeweave", 650, "documentation"),
    ("scopeweave", 625, "documentation"),
    ("newsdom-api", 782, "documentation"),
    ("kaefa", 81, "documentation"),
    ("kaefa", 82, "documentation"),
    ("aFIPC", 261, "documentation"),
    ("nonnest2", 115, "documentation"),
    ("wardnet", 130, "documentation"),
    ("four-pillars", 31, "documentation"),
    ("enterprise-architecture-core", 18, "documentation"),
    ("enterprise-architecture-core", 37, "documentation"),
]


def test_repository_label_taxonomy_maps_evidence_backed_types() -> None:
    """Common semantic types and reviewed targets remain explicit and stable."""

    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["type"] == {
        "feature": "enhancement",
        "bug": "bug",
        "documentation": "documentation",
    }
    assert payload["assignments"] == [
        {"repository": repository, "issue": issue, "type": semantic_type}
        for repository, issue, semantic_type in EXPECTED_ASSIGNMENTS
    ]
    assert len(set(payload["type"].values())) == len(payload["type"])
    assert len({(repository, issue) for repository, issue, _ in EXPECTED_ASSIGNMENTS}) == len(
        EXPECTED_ASSIGNMENTS
    )


def test_repository_label_operating_record_matches_assignment_inventory() -> None:
    """Operator records must enumerate the exact active taxonomy inventory."""

    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    assignments = payload["assignments"]
    operating_record = "\n".join(
        path.read_text(encoding="utf-8") for path in OPERATING_RECORDS
    )

    assert (
        f"explicit label assignments cover {len(assignments)} active evidence-backed targets"
        in operating_record
    )
    for assignment in assignments:
        target = f"`ContextualWisdomLab/{assignment['repository']}#{assignment['issue']}`"
        assert target in operating_record
