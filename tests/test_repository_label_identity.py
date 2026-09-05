"""Repository identity regressions for label desired state."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_labels.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_labels", SCRIPT)
assert SPEC and SPEC.loader
LABELS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LABELS)


def test_taxonomy_rejects_case_only_repository_collisions(tmp_path: Path) -> None:
    """Assignments cannot spell one GitHub repository with conflicting casing."""

    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "type": {"feature": "enhancement"},
                "assignments": [
                    {"repository": "Repo", "issue": 1, "type": "feature"},
                    {"repository": "repo", "issue": 2, "type": "feature"},
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LABELS.TaxonomyError, match="casing collision"):
        LABELS.load_taxonomy(path)


def test_taxonomy_rejects_case_only_managed_label_collisions(tmp_path: Path) -> None:
    """Managed label identities cannot differ only by GitHub-insensitive casing."""

    path = tmp_path / "taxonomy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "type": {"feature": "Enhancement", "bug": "enhancement"},
                "assignments": [],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(LABELS.TaxonomyError, match="unique ignoring case"):
        LABELS.load_taxonomy(path)


def test_label_filters_normalize_case_and_reject_unknown_repositories() -> None:
    """Narrow reconciliation filters use GitHub identity but keep reviewed casing."""

    assignments = [
        {"repository": "Repo", "issue": 1, "type": "feature"},
        {"repository": "OtherRepo", "issue": 2, "type": "feature"},
    ]

    assert LABELS._select_repository_identities([], assignments) == set()
    assert LABELS._select_repository_identities(
        ["repo", "REPO", "OtherRepo"], assignments
    ) == {"repo", "otherrepo"}
    with pytest.raises(LABELS.TaxonomyError, match="undeclared"):
        LABELS._select_repository_identities(["missing"], assignments)


def test_managed_label_comparison_is_case_insensitive(monkeypatch) -> None:
    """Existing differently cased managed labels do not churn on every run."""

    calls = []

    def gh_api(method, endpoint, body=None, allow_not_found=False):
        calls.append((method, endpoint, body, allow_not_found))
        return json.dumps(
            {"labels": [{"name": "DOCUMENTATION"}, {"name": "status: ready"}]}
        )

    monkeypatch.setattr(LABELS, "_gh_api", gh_api)
    item = {"repository": "Repo", "issue": 1, "type": "documentation"}
    mappings = {"bug": "Bug", "documentation": "documentation"}

    LABELS.reconcile_assignment(item, mappings)
    LABELS.verify_assignment(item, mappings)

    assert [call[0] for call in calls] == ["GET", "GET"]
    assert LABELS._label_names(
        {"labels": ["Bug", {"name": "BUG"}, {"name": "Other"}]}
    ) == ["Bug", "Other"]
