"""Contracts for preserving GitHub Actions-backed Pages deployments."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_metadata.py"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_metadata_pages", SCRIPT)
assert SPEC and SPEC.loader
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


def desired(**overrides):
    """Return a minimal valid workflow-Pages desired-state record."""

    state = {
        "description": "Useful product.",
        "topics": ["python"],
        "deepwiki": False,
        "pages": True,
        "pages_mode": "workflow",
    }
    state.update(overrides)
    return state


def test_manifest_accepts_explicit_workflow_pages_mode() -> None:
    """Workflow-backed Pages intent is explicit without changing legacy records."""

    state = desired()
    assert RECONCILER._validate_repository("Repo", state) == state
    legacy = {key: value for key, value in state.items() if key != "pages_mode"}
    assert RECONCILER._validate_repository("Repo", legacy) == legacy

    with pytest.raises(RECONCILER.ManifestError, match="pages_mode"):
        RECONCILER._validate_repository("Repo", desired(pages_mode="other"))
    with pytest.raises(RECONCILER.ManifestError, match="only valid"):
        RECONCILER._validate_repository("Repo", desired(pages=False))


def test_workflow_pages_definition_probe_uses_standard_reviewed_path(monkeypatch) -> None:
    """Workflow-mode source discovery probes only the standard reviewed Pages path."""

    seen = []

    def repository_file_exists(repository, default_branch, path):
        seen.append((repository, default_branch, path))
        return True

    monkeypatch.setattr(RECONCILER, "_repository_file_exists", repository_file_exists)

    assert RECONCILER._workflow_pages_definition_exists("Repo", "main")
    assert seen == [("Repo", "main", ".github/workflows/pages.yml")]


def test_workflow_pages_precondition_rejects_missing_reviewed_workflow(monkeypatch) -> None:
    """Workflow intent fails before mutation when the reviewed Pages workflow is absent."""

    monkeypatch.setattr(
        RECONCILER, "_workflow_pages_definition_exists", lambda *args: False
    )

    with pytest.raises(RuntimeError, match=r"\.github/workflows/pages\.yml"):
        RECONCILER._pages_precondition("Repo", "main", desired())


def test_workflow_pages_reconcile_preserves_live_actions_mode(monkeypatch) -> None:
    """A reviewed Actions-backed Pages site is verified rather than rewritten to legacy."""

    calls = []

    def gh_api(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint.endswith("/topics"):
            return json.dumps({"names": ["python"]})
        if endpoint.endswith("/pages"):
            return json.dumps({"build_type": "workflow"})
        return json.dumps(
            {"default_branch": "main", "description": "Useful product."}
        )

    monkeypatch.setattr(RECONCILER, "_gh_api", gh_api)
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    monkeypatch.setattr(
        RECONCILER, "_workflow_pages_definition_exists", lambda *args: True
    )
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: True)

    RECONCILER.reconcile_repository("Repo", desired())

    page_writes = [
        call
        for call in calls
        if call[1].endswith("/pages") and call[0] in {"POST", "PUT", "DELETE"}
    ]
    assert page_writes == []


def test_workflow_pages_reconcile_fails_closed_on_missing_or_wrong_mode(monkeypatch) -> None:
    """Workflow intent never creates or converts Pages through the legacy settings API."""

    monkeypatch.setattr(
        RECONCILER,
        "_gh_api",
        lambda method, endpoint, **kwargs: (
            json.dumps({"names": ["python"]})
            if endpoint.endswith("/topics")
            else json.dumps({"default_branch": "main", "description": "Useful product."})
        ),
    )
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    monkeypatch.setattr(
        RECONCILER, "_workflow_pages_definition_exists", lambda *args: True
    )
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: False)
    with pytest.raises(RuntimeError, match="not configured"):
        RECONCILER.reconcile_repository("Repo", desired())

    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: True)
    monkeypatch.setattr(
        RECONCILER,
        "_pages_configuration",
        lambda *args: {"build_type": "legacy", "source": {"branch": "main", "path": "/docs"}},
    )
    with pytest.raises(RuntimeError, match="not Actions-backed"):
        RECONCILER.reconcile_repository("Repo", desired())


def test_workflow_pages_verification_rejects_missing_reviewed_source(monkeypatch) -> None:
    """Live verification fails closed if the declared workflow source disappears."""

    monkeypatch.setattr(
        RECONCILER,
        "_gh_api",
        lambda method, endpoint, **kwargs: (
            json.dumps({"names": ["python"]})
            if endpoint.endswith("/topics")
            else json.dumps({"default_branch": "main", "description": "Useful product."})
        ),
    )
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    monkeypatch.setattr(
        RECONCILER, "_workflow_pages_definition_exists", lambda *args: False
    )

    with pytest.raises(RuntimeError, match="workflow source did not converge"):
        RECONCILER.verify_repository("Repo", desired())


def test_workflow_pages_verification_requires_live_publication(monkeypatch) -> None:
    """Workflow mode still requires exact live configuration and published content evidence."""

    monkeypatch.setattr(
        RECONCILER,
        "_gh_api",
        lambda method, endpoint, **kwargs: (
            json.dumps({"names": ["python"]})
            if endpoint.endswith("/topics")
            else json.dumps({"default_branch": "main", "description": "Useful product."})
        ),
    )
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    monkeypatch.setattr(
        RECONCILER, "_workflow_pages_definition_exists", lambda *args: True
    )
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: True)
    current = {
        "build_type": "workflow",
        "status": "built",
        "html_url": "https://contextualwisdomlab.github.io/repo/",
    }
    monkeypatch.setattr(RECONCILER, "_pages_configuration", lambda *args: current)
    seen = []
    monkeypatch.setattr(
        RECONCILER,
        "_pages_publication_ready",
        lambda repository, pages: seen.append((repository, pages)),
    )

    RECONCILER.verify_repository("Repo", desired())
    assert seen == [("Repo", current)]

    monkeypatch.setattr(
        RECONCILER, "_pages_configuration", lambda *args: {"build_type": "legacy"}
    )
    with pytest.raises(RuntimeError, match="deployment mode"):
        RECONCILER.verify_repository("Repo", desired())
