"""Contracts for the organization-wide repository label taxonomy."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "config" / "repository-label-taxonomy.json"


def test_repository_label_taxonomy_maps_evidence_backed_types() -> None:
    """Common semantic types resolve to stable existing GitHub labels."""

    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))

    assert payload == {
        "schema_version": 1,
        "type": {
            "feature": "enhancement",
            "bug": "bug",
            "documentation": "documentation",
        },
    }
    assert len(set(payload["type"].values())) == len(payload["type"])
