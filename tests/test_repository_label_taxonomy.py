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
    ]
    assert len(set(payload["type"].values())) == len(payload["type"])
