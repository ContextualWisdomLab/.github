"""Contracts for the organization-wide repository label taxonomy."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "config" / "repository-label-taxonomy.json"


def test_repository_label_taxonomy_maps_evidence_backed_types() -> None:
    """Common semantic types and reviewed targets remain explicit and stable."""

    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["type"] == {
        "feature": "enhancement",
        "bug": "bug",
        "documentation": "documentation",
    }
    # Keep assignments exact so reviewed target drift cannot silently escape CI.
    assert payload["assignments"] == [
        {"repository": ".github", "issue": 1582, "type": "feature"},
        {"repository": ".github", "issue": 1622, "type": "feature"},
        {"repository": ".github", "issue": 1625, "type": "bug"},
        {"repository": ".github", "issue": 1634, "type": "documentation"},
        {"repository": "CalendarWeave", "issue": 1, "type": "documentation"},
        {"repository": "ConceptWeave", "issue": 1, "type": "feature"},
        {
            "repository": "context-graph-contracts",
            "issue": 20,
            "type": "documentation",
        },
        {"repository": "RankWeave", "issue": 40, "type": "documentation"},
        {"repository": "fast-mlsirm", "issue": 1717, "type": "documentation"},
        {"repository": "EgressWeave", "issue": 231, "type": "documentation"},
        {
            "repository": "psychometrics-commons",
            "issue": 442,
            "type": "documentation",
        },
        {
            "repository": "contextual-orchestrator",
            "issue": 994,
            "type": "documentation",
        },
        {
            "repository": "contextual-orchestrator",
            "issue": 1003,
            "type": "documentation",
        },
        {"repository": "appguardrail", "issue": 1077, "type": "documentation"},
        {"repository": "naruon", "issue": 1513, "type": "documentation"},
        {"repository": "LineageWeave", "issue": 908, "type": "documentation"},
        {
            "repository": "ContextualWisdomLab.github.io",
            "issue": 203,
            "type": "documentation",
        },
        {"repository": "TEPP", "issue": 435, "type": "documentation"},
        {
            "repository": "semantic-data-portal",
            "issue": 72,
            "type": "documentation",
        },
        {"repository": "Orgmetra", "issue": 160, "type": "documentation"},
        {
            "repository": "learning-interoperability-contracts",
            "issue": 1,
            "type": "feature",
        },
        {"repository": "noema", "issue": 530, "type": "feature"},
        {"repository": "bandscope", "issue": 1125, "type": "documentation"},
        {"repository": "saju-caldav", "issue": 44, "type": "documentation"},
        {"repository": "OriginWeave", "issue": 274, "type": "documentation"},
        {
            "repository": "semantic-data-portal",
            "issue": 90,
            "type": "documentation",
        },
        {
            "repository": "accounting-information-platform",
            "issue": 45,
            "type": "documentation",
        },
        {"repository": "clearfolio", "issue": 538, "type": "documentation"},
        {"repository": "pg-erd-cloud", "issue": 1046, "type": "documentation"},
        {"repository": "DiagramWeave", "issue": 34, "type": "documentation"},
        {"repository": "keyverse", "issue": 127, "type": "documentation"},
        {
            "repository": "mhtml-etl-gateway",
            "issue": 56,
            "type": "documentation",
        },
        {"repository": "j-planner", "issue": 2, "type": "documentation"},
        {
            "repository": "learning-record-store",
            "issue": 1,
            "type": "documentation",
        },
        {
            "repository": "learning-record-store",
            "issue": 7,
            "type": "documentation",
        },
        {
            "repository": "learning-content-studio",
            "issue": 1,
            "type": "documentation",
        },
        {
            "repository": "learning-content-studio",
            "issue": 8,
            "type": "documentation",
        },
        {
            "repository": "learning-management-platform",
            "issue": 1,
            "type": "documentation",
        },
        {
            "repository": "metering-billing-platform",
            "issue": 175,
            "type": "documentation",
        },
        {"repository": "PolicyWeave", "issue": 1, "type": "feature"},
        {
            "repository": "supply-chain-control-plane",
            "issue": 1,
            "type": "feature",
        },
    ]
    assert len(set(payload["type"].values())) == len(payload["type"])
