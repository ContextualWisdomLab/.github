"""Regression contracts for label-taxonomy workflow path coverage."""

from __future__ import annotations

from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/repository-metadata-reconcile.yml")
OPERATING_RECORD_PATH = "docs/doctoring/repository-label-taxonomy-wave-3.md"


def test_taxonomy_operating_record_change_triggers_reconciliation() -> None:
    """Every file consumed by the taxonomy inventory contract must wake validation."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    pull_request_paths = workflow_text.split("  pull_request:\n    paths:\n", 1)[1].split(
        "  schedule:\n", 1
    )[0]
    assert f'      - "{OPERATING_RECORD_PATH}"' in pull_request_paths
