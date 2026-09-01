"""Contracts for fleet repository metadata reconciliation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_metadata.py"
MANIFEST = ROOT / "config" / "repository-metadata.json"


def test_metadata_reconciler_validates_declared_repository_state() -> None:
    """The central reconciler must validate a deterministic desired-state manifest."""

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--manifest", str(MANIFEST), "--validate-only"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_metadata_manifest_declares_exact_casing_and_public_surfaces() -> None:
    """Desired state must preserve exact repository casing and public metadata intent."""

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    repositories = payload["repositories"]

    calendar = repositories["CalendarWeave"]
    assert calendar["description"] == "CalendarWeave — governed calendar resources, iCalendar semantics, and interoperable scheduling infrastructure."
    assert calendar["deepwiki"] is True
    assert calendar["pages"] is True
    assert "calendar" in calendar["topics"]
    assert "icalendar" in calendar["topics"]

    concept = repositories["ConceptWeave"]
    assert concept["description"] == "ConceptWeave — turn enterprise data into governed semantic models and reusable meaning."
    assert concept["deepwiki"] is True
    assert concept["pages"] is True
    assert "semantic-model" in concept["topics"]
    assert "ontology" in concept["topics"]

    contracts = repositories["context-graph-contracts"]
    assert contracts["description"] == "Context Graph Contracts — versioned interoperability contracts for context, lineage, provenance, and architecture facts."
    assert contracts["deepwiki"] is True
    assert contracts["pages"] is True
    assert "interoperability" in contracts["topics"]
    assert "cloudevents" in contracts["topics"]
