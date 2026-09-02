"""Contracts for the organization-wide repository label taxonomy."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TAXONOMY = ROOT / "config" / "repository-label-taxonomy.json"
OPERATING_RECORD = ROOT / "docs" / "doctoring" / "repository-public-surface-reconciliation.md"
OPERATING_RECORD_SUPPLEMENT = (
    ROOT / "docs" / "doctoring" / "repository-label-taxonomy-wave-3.md"
)
EXPECTED_TAXONOMY_BLOB_SHA = "7ad21f9bf2303caad344132fcc425f95790aa3cb"


def _git_blob_sha(path: Path) -> str:
    """Return Git's content-addressed blob identity for ``path``."""

    data = path.read_bytes()
    header = f"blob {len(data)}\0".encode("ascii")
    return hashlib.sha1(header + data, usedforsecurity=False).hexdigest()


def test_repository_label_taxonomy_maps_evidence_backed_types() -> None:
    """Semantic mappings and the reviewed assignment inventory stay exact."""

    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["type"] == {
        "feature": "enhancement",
        "bug": "bug",
        "documentation": "documentation",
    }
    # Pin the complete human-reviewed taxonomy, not only a prefix of the list.
    # Git blob identity is intentionally used as a compact exact-inventory
    # contract; SHA-1 here is Git object addressing, not a security primitive.
    assert _git_blob_sha(TAXONOMY) == EXPECTED_TAXONOMY_BLOB_SHA

    assignments = payload["assignments"]
    identities = [
        (assignment["repository"], assignment["issue"]) for assignment in assignments
    ]
    assert len(identities) == len(set(identities))
    assert all(assignment["type"] in payload["type"] for assignment in assignments)
    assert len(set(payload["type"].values())) == len(payload["type"])


def test_repository_label_operating_record_matches_assignment_inventory() -> None:
    """The operator record must enumerate the exact active taxonomy inventory."""

    payload = json.loads(TAXONOMY.read_text(encoding="utf-8"))
    assignments = payload["assignments"]
    operating_record = "\n".join(
        (
            OPERATING_RECORD.read_text(encoding="utf-8"),
            OPERATING_RECORD_SUPPLEMENT.read_text(encoding="utf-8"),
        )
    )

    assert (
        f"explicit label assignments cover {len(assignments)} active evidence-backed targets"
        in operating_record
    )
    for assignment in assignments:
        target = (
            f"`ContextualWisdomLab/{assignment['repository']}#{assignment['issue']}`"
        )
        assert target in operating_record
