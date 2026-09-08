"""Repository identity regressions for metadata desired state."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_metadata.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_metadata", SCRIPT)
assert SPEC and SPEC.loader
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


def desired() -> dict[str, object]:
    """Return a minimal valid desired-state record."""

    return {
        "description": "Useful product.",
        "topics": ["python"],
        "deepwiki": False,
        "pages": False,
    }


def test_manifest_rejects_case_only_repository_collisions(tmp_path: Path) -> None:
    """GitHub case aliases cannot own conflicting desired-state records."""

    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": {"Repo": desired(), "repo": desired()},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(RECONCILER.ManifestError, match="casing collision"):
        RECONCILER.load_manifest(path)


def test_repository_filters_use_reviewed_casing_and_deduplicate_aliases() -> None:
    """Operator filters normalize GitHub identity without changing API casing."""

    repositories = {"Repo": desired(), "OtherRepo": desired()}

    assert RECONCILER._select_repositories([], repositories) == ["Repo", "OtherRepo"]
    assert RECONCILER._select_repositories(
        ["repo", "REPO", "OtherRepo"], repositories
    ) == ["Repo", "OtherRepo"]
    with pytest.raises(RECONCILER.ManifestError, match="undeclared"):
        RECONCILER._select_repositories(["missing"], repositories)
