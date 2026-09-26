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
    public_surfaces = {
        "CalendarWeave": ("calendar", "icalendar"),
        "ConceptWeave": ("semantic-model", "ontology"),
        "context-graph-contracts": ("interoperability", "cloudevents"),
        "enterprise-architecture-core": ("enterprise-architecture", "context-map"),
        "EmbedRelay": ("embeddings", "data-migration"),
        "pg-llm-batch": ("postgresql", "batch-processing"),
        "inkspan": ("markdown-editor", "collaborative-editing"),
        "appguardrail": ("application-security", "sarif"),
        "ELUNVERA": ("crm", "relationship-intelligence"),
        "four-pillars": ("four-pillars", "korean-calendar"),
        "quarantine-sandbox-runtime": ("sandbox", "container-security"),
        "TEPP": ("psychometrics", "temporal-analysis"),
        "wardnet": ("web-application-firewall", "security-operations"),
        "codec-carver": ("audio-processing", "speech-to-text"),
        "naruon": ("email-client", "personal-information-management"),
        "newsdom-api": ("pdf-parsing", "dom"),
        "scopeweave": ("wbs", "project-planning"),
        "macos_utility_packs": ("macos", "bootstrap"),
        "kaefa": ("automated-analysis", "item-response-theory"),
        "linux-cluster-ops": ("cluster-management", "sysadmin"),
        "ThreadWeave": ("rfc5256", "python"),
        "RankWeave": ("information-retrieval", "trec"),
        "fast-mlsirm": ("psychometrics", "rust"),
        "EgressWeave": ("ssrf", "python"),
        "psychometrics-commons": ("psychometrics", "rust"),
        "keyverse": ("identity", "openid-connect"),
        "OriginWeave": ("browser-automation", "ai-agents"),
        "accounting-information-platform": ("accounting", "ledger"),
        "pg-erd-cloud": ("erd", "postgresql"),
        "clearfolio": ("document-viewer", "document-conversion"),
        "DiagramWeave": ("diagram-editor", "plantuml"),
        "semantic-data-portal": ("data-catalog", "semantic-search"),
        "contextual-orchestrator": ("llm-orchestration", "model-routing"),
        "noema": ("control-plane", "oidc"),
        "mhtml-etl-gateway": ("mhtml", "etl"),
        "PolicyWeave": ("privacy-policy", "typescript"),
        "supply-chain-control-plane": ("supply-chain", "rust"),
        "learning-management-platform": ("learning-management-system", "rust"),
        "learning-content-studio": ("lcms", "content-authoring"),
        "learning-record-store": ("learning-record-store", "xapi"),
        "bandscope": ("audio-analysis", "rehearsal"),
        "saju-caldav": ("caldav", "four-pillars"),
        "governance-risk-compliance": ("governance", "grc"),
        "metering-billing-platform": ("metering", "billing"),
        "learning-interoperability-contracts": ("xapi", "json-schema"),
        "litellm-patched-proxy": ("llm-proxy", "supply-chain-security"),
        "pingora-gateway": ("reverse-proxy", "rust"),
        "global-hs-trade": ("international-trade", "hs-code"),
        "LineageWeave": ("data-lineage", "knowledge-graph"),
        "j-planner": ("travel-planner", "pwa"),
        "disksage": ("disk-cleanup", "rust"),
        "Veilpick": ("web-acquisition", "rust"),
    }
    topics_only = {
        "BizPlanningWizard": ("business-planning", "productivity"),
        "litellm": ("llm-gateway", "openai-compatible"),
        "opencode": ("coding-agent", "developer-tools"),
        "orca": ("ai-orchestration", "git-worktrees"),
    }
    assert set(repositories) == set(public_surfaces) | set(topics_only)
    for repository, required_topics in public_surfaces.items():
        state = repositories[repository]
        assert state["deepwiki"] is True
        assert state["pages"] is True
        assert all(topic in state["topics"] for topic in required_topics)
    for repository, required_topics in topics_only.items():
        state = repositories[repository]
        assert state["deepwiki"] is False
        assert state["pages"] is False
        assert all(topic in state["topics"] for topic in required_topics)
    assert repositories["j-planner"]["pages_mode"] == "legacy-root"
    assert repositories["j-planner"]["homepage"] == (
        "https://contextualwisdomlab.github.io/j-planner/"
    )
    assert repositories["LineageWeave"]["pages_mode"] == "workflow"
    assert repositories["LineageWeave"]["pages_workflow"] == (
        ".github/workflows/ontology-pages.yml"
    )
    assert repositories["LineageWeave"]["homepage"] == (
        "https://contextualwisdomlab.github.io/LineageWeave/"
    )
    assert repositories["pingora-gateway"]["pages_mode"] == "workflow"
    assert repositories["pingora-gateway"]["homepage"] == (
        "https://contextualwisdomlab.github.io/pingora-gateway/"
    )
    assert repositories["enterprise-architecture-core"]["homepage"] == (
        "https://contextualwisdomlab.github.io/enterprise-architecture-core/"
    )
    assert repositories["EmbedRelay"]["homepage"] == (
        "https://contextualwisdomlab.github.io/EmbedRelay/"
    )
    assert repositories["pg-llm-batch"]["homepage"] == (
        "https://contextualwisdomlab.github.io/pg-llm-batch/"
    )
    assert repositories["inkspan"]["homepage"] == (
        "https://contextualwisdomlab.github.io/inkspan/"
    )
    assert repositories["appguardrail"]["homepage"] == (
        "https://contextualwisdomlab.github.io/appguardrail/"
    )
    assert repositories["ELUNVERA"]["homepage"] == (
        "https://contextualwisdomlab.github.io/ELUNVERA/"
    )
    assert repositories["four-pillars"]["homepage"] == (
        "https://contextualwisdomlab.github.io/four-pillars/"
    )
    assert repositories["quarantine-sandbox-runtime"]["homepage"] == (
        "https://contextualwisdomlab.github.io/quarantine-sandbox-runtime/"
    )
    assert repositories["TEPP"]["homepage"] == (
        "https://contextualwisdomlab.github.io/TEPP/"
    )
    assert repositories["wardnet"]["homepage"] == (
        "https://contextualwisdomlab.github.io/wardnet/"
    )
    assert repositories["codec-carver"]["homepage"] == (
        "https://contextualwisdomlab.github.io/codec-carver/"
    )
    assert repositories["naruon"]["homepage"] == (
        "https://contextualwisdomlab.github.io/naruon/"
    )
    assert repositories["newsdom-api"]["pages_mode"] == "workflow"
    assert repositories["newsdom-api"]["pages_workflow"] == (
        ".github/workflows/gh-pages.yml"
    )
    assert repositories["newsdom-api"]["homepage"] == (
        "https://contextualwisdomlab.github.io/newsdom-api/"
    )

    assert repositories["scopeweave"]["pages_mode"] == "workflow"
    assert repositories["scopeweave"]["homepage"] == (
        "https://contextualwisdomlab.github.io/scopeweave/"
    )

    assert repositories["macos_utility_packs"]["homepage"] == (
        "https://contextualwisdomlab.github.io/macos_utility_packs/"
    )

    assert repositories["kaefa"]["pages_mode"] == "legacy-root"
    assert repositories["kaefa"]["pages_branch"] == "gh-pages"
    assert "homepage" not in repositories["kaefa"]
    assert repositories["linux-cluster-ops"]["homepage"] == (
        "https://contextualwisdomlab.github.io/linux-cluster-ops/"
    )


def test_require_exact_dict_and_repository_validation() -> None:
    """Malformed desired state fails closed across every field family."""

    assert RECONCILER._require_exact_dict({}, field="x") == {}
    with pytest.raises(RECONCILER.ManifestError, match="must be an object"):
        RECONCILER._require_exact_dict([], field="x")

    valid = desired()
    assert RECONCILER._validate_repository("Repo", valid) == valid
    for name in [1, "bad name", "Repo..Name", "Repo."]:
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

    assert RECONCILER._validate_repository(
        "Repo", desired(homepage=None)
    )["homepage"] is None
    assert RECONCILER._validate_repository(
        "Repo", desired(homepage="https://example.com/docs")
    )["homepage"] == "https://example.com/docs"
    for homepage in [
        " https://example.com",
        "http://example.com",
        "not-a-url",
        "https://localhost/docs",
