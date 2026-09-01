"""Behavioral contracts for fleet repository metadata reconciliation."""

from __future__ import annotations

import argparse
import importlib.util
import json
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ci" / "reconcile_repository_metadata.py"
MANIFEST = ROOT / "config" / "repository-metadata.json"
SPEC = importlib.util.spec_from_file_location("reconcile_repository_metadata", SCRIPT)
assert SPEC and SPEC.loader
RECONCILER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECONCILER)


def desired(**overrides):
    """Return a minimal valid repository desired-state record."""

    data = {
        "description": "Useful product.",
        "topics": ["python"],
        "deepwiki": False,
        "pages": False,
    }
    data.update(overrides)
    return data


def write_manifest(tmp_path, repositories=None, **root_overrides):
    """Write a test manifest and return its path."""

    payload = {
        "schema_version": 1,
        "organization": RECONCILER.ORGANIZATION,
        "repositories": repositories or {"Repo": desired()},
    }
    payload.update(root_overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def completed(code=0, out="", err=""):
    """Return a compact subprocess result for GitHub CLI probes."""

    return subprocess.CompletedProcess(
        args=["gh"], returncode=code, stdout=out, stderr=err
    )


def test_metadata_manifest_declares_exact_casing_and_public_surfaces() -> None:
    """The reviewed manifest preserves exact repository casing and surface intent."""

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    repositories = payload["repositories"]
    expected = {
        "CalendarWeave": ("calendar", "icalendar"),
        "ConceptWeave": ("semantic-model", "ontology"),
        "context-graph-contracts": ("interoperability", "cloudevents"),
        "ThreadWeave": ("rfc5256", "python"),
        "RankWeave": ("information-retrieval", "trec"),
        "fast-mlsirm": ("psychometrics", "rust"),
        "EgressWeave": ("ssrf", "python"),
        "psychometrics-commons": ("psychometrics", "rust"),
        "LineageWeave": ("data-lineage", "python"),
        "contextual-orchestrator": ("llm-orchestration", "control-plane"),
        "appguardrail": ("security", "static-analysis"),
        "naruon": ("ai-workspace", "email"),
    }
    assert set(repositories) == set(expected)
    for repository, required_topics in expected.items():
        state = repositories[repository]
        assert state["deepwiki"] is True
        assert state["pages"] is True
        assert all(topic in state["topics"] for topic in required_topics)


def test_require_exact_dict_and_repository_validation() -> None:
    """Malformed desired state fails closed across every field family."""

    assert RECONCILER._require_exact_dict({}, field="x") == {}
    with pytest.raises(RECONCILER.ManifestError, match="must be an object"):
        RECONCILER._require_exact_dict([], field="x")

    valid = desired()
    assert RECONCILER._validate_repository("Repo", valid) == valid
    for name in [1, "bad name"]:
        with pytest.raises(RECONCILER.ManifestError, match="exact GitHub-safe casing"):
            RECONCILER._validate_repository(name, valid)
    with pytest.raises(RECONCILER.ManifestError, match="contain exactly"):
        RECONCILER._validate_repository("Repo", {**valid, "extra": True})

    descriptions = [
        None,
        "",
        "x" * 351,
        "do not publish",
        "issue #7",
        "https://example.com",
    ]
    for description in descriptions:
        with pytest.raises(RECONCILER.ManifestError):
            RECONCILER._validate_repository(
                "Repo", {**valid, "description": description}
            )

    topic_cases = [None, [], ["x"] * 21, [1], ["Bad_Topic"], ["dup", "dup"]]
    for topics in topic_cases:
        with pytest.raises(RECONCILER.ManifestError):
            RECONCILER._validate_repository("Repo", {**valid, "topics": topics})

    for field, value in [("deepwiki", 1), ("pages", "yes")]:
        with pytest.raises(RECONCILER.ManifestError):
            RECONCILER._validate_repository("Repo", {**valid, field: value})


def test_load_manifest_contracts(tmp_path) -> None:
    """Manifest root schema, ownership, and non-empty fleet scope are enforced."""

    path = write_manifest(tmp_path)
    assert list(RECONCILER.load_manifest(path)) == ["Repo"]

    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(RECONCILER.ManifestError, match="manifest must be an object"):
        RECONCILER.load_manifest(path)

    cases = [
        (
            {
                "schema_version": 1,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": {},
                "extra": 1,
            },
            "unexpected key",
        ),
        (
            {
                "schema_version": 2,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": {},
            },
            "schema or organization",
        ),
        (
            {
                "schema_version": True,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": {"Repo": desired()},
            },
            "schema or organization",
        ),
        (
            {"schema_version": 1, "organization": "Other", "repositories": {}},
            "schema or organization",
        ),
        (
            {
                "schema_version": 1,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": [],
            },
            "repositories must be an object",
        ),
        (
            {
                "schema_version": 1,
                "organization": RECONCILER.ORGANIZATION,
                "repositories": {},
            },
            "at least one repository",
        ),
    ]
    for payload, message in cases:
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(RECONCILER.ManifestError, match=message):
            RECONCILER.load_manifest(path)


def test_gh_api_builds_requests_and_fails_closed(monkeypatch) -> None:
    """GitHub API writes serialize bounded JSON and reject non-zero exits."""

    seen = []
    monkeypatch.setattr(
        RECONCILER.subprocess,
        "run",
        lambda *args, **kwargs: seen.append((args, kwargs)) or completed(out="ok"),
    )
    assert (
        RECONCILER._gh_api(
            "PATCH", "repos/x/y", fields={"a": "b"}, body={"z": 1}
        )
        == "ok"
    )
    args, kwargs = seen[0]
    assert args[0][:5] == ["gh", "api", "--method", "PATCH", "repos/x/y"]
    assert "--input" in args[0] and "--field" in args[0]
    assert kwargs["input"] == '{"z":1}'

    monkeypatch.setattr(
        RECONCILER.subprocess,
        "run",
        lambda *args, **kwargs: completed(code=1),
    )
    with pytest.raises(RuntimeError, match="GitHub API request failed"):
        RECONCILER._gh_api("GET", "repos/x/y")


def test_pages_and_docs_probes(monkeypatch) -> None:
    """Pages and source probes distinguish present, absent, and unknown states."""

    responses = iter(
        [completed(), completed(code=1, err="HTTP 404"), completed(code=1, err="boom")]
    )
    monkeypatch.setattr(
        RECONCILER.subprocess, "run", lambda *args, **kwargs: next(responses)
    )
    assert RECONCILER._pages_state("Repo") is True
    assert RECONCILER._pages_state("Repo") is False
    with pytest.raises(RuntimeError, match="GitHub API request failed"):
        RECONCILER._pages_state("Repo")

    responses = iter(
        [completed(), completed(code=1, err="HTTP 404"), completed(code=1, err="boom")]
    )
    monkeypatch.setattr(
        RECONCILER.subprocess, "run", lambda *args, **kwargs: next(responses)
    )
    assert RECONCILER._docs_index_state("Repo", "main") is True
    assert RECONCILER._docs_index_state("Repo", "main") is False
    with pytest.raises(RuntimeError, match="GitHub API request failed"):
        RECONCILER._docs_index_state("Repo", "main")


def test_repository_metadata_cli_validation(monkeypatch, tmp_path) -> None:
    """CLI validation has no GitHub side effects and validates filters."""

    path = write_manifest(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--manifest", str(path), "--validate-only"])
    runpy.run_path(str(SCRIPT), run_name="__main__")

    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--manifest", str(path), "--repository", "missing", "--validate-only"],
    )
    with pytest.raises(SystemExit):
        runpy.run_path(str(SCRIPT), run_name="__main__")
