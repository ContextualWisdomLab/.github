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
    assert payload["assignments"] == [
        {"repository": ".github", "issue": 1582, "type": "feature"},
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
        {"repository": "noema", "issue": 530, "type": "feature"},
    ]
    assert len(set(payload["type"].values())) == len(payload["type"])
