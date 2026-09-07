"""Focused convergence regressions for repository metadata reconciliation."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_metadata.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_metadata", SCRIPT)
assert SPEC and SPEC.loader
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


def desired(**overrides):
    """Return one minimal desired-state record."""

    state = {
        "description": "Useful product.",
        "topics": ["python", "tooling"],
        "deepwiki": False,
        "pages": False,
    }
    state.update(overrides)
    return state


def test_topic_order_does_not_trigger_rewrite(monkeypatch) -> None:
    """GitHub topic ordering is treated as presentation, not desired-state drift."""

    calls = []

    def gh_api(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint.endswith("/topics"):
            return json.dumps({"names": ["tooling", "python"]})
        return json.dumps(
            {"default_branch": "main", "description": "Useful product."}
        )

    monkeypatch.setattr(RECONCILER, "_gh_api", gh_api)
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: False)

    RECONCILER.reconcile_repository("Repo", desired())

    assert [method for method, _, _ in calls] == ["GET", "GET"]


def test_duplicate_repository_filters_run_once(monkeypatch, tmp_path) -> None:
    """Repeated narrow repository arguments never duplicate privileged writes."""

    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": {"Repo": desired(topics=["python"])},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("GH_TOKEN", "token")
    monkeypatch.setattr(
        RECONCILER,
        "parse_args",
        lambda: argparse.Namespace(
            manifest=manifest,
            validate_only=False,
            repository=["Repo", "Repo", "Repo"],
        ),
    )
    seen = []
    monkeypatch.setattr(
        RECONCILER,
        "reconcile_repository",
        lambda repository, state: seen.append(repository),
    )

    assert RECONCILER.main() == 0
    assert seen == ["Repo"]
