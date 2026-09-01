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
        "keyverse": ("identity", "openid-connect"),
        "OriginWeave": ("browser-automation", "ai-agents"),
        "accounting-information-platform": ("accounting", "ledger"),
        "pg-erd-cloud": ("erd", "postgresql"),
        "clearfolio": ("document-viewer", "document-conversion"),
        "DiagramWeave": ("diagram-editor", "plantuml"),
        "semantic-data-portal": ("data-catalog", "semantic-search"),
        "contextual-orchestrator": ("llm-orchestration", "model-routing"),
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
    assert RECONCILER._pages_exists("Repo") is True
    assert RECONCILER._pages_exists("Repo") is False
    with pytest.raises(RuntimeError, match="Pages state"):
        RECONCILER._pages_exists("Repo")

    responses = iter(
        [
            completed(out='{"type":"file"}'),
            completed(code=1, out="Not Found"),
            completed(code=1, err="boom"),
        ]
    )
    monkeypatch.setattr(
        RECONCILER.subprocess, "run", lambda *args, **kwargs: next(responses)
    )
    assert RECONCILER._docs_index_exists("Repo", "main") is True
    assert RECONCILER._docs_index_exists("Repo", "main") is False
    with pytest.raises(RuntimeError, match="Pages source state"):
        RECONCILER._docs_index_exists("Repo", "main")


def test_pages_configuration_contracts(monkeypatch) -> None:
    """Pages state is parsed exactly and converged legacy /docs sites are recognized."""

    monkeypatch.setattr(
        RECONCILER,
        "_gh_api",
        lambda *args, **kwargs: json.dumps(
            {
                "build_type": "legacy",
                "source": {"branch": "main", "path": "/docs"},
            }
        ),
    )
    current = RECONCILER._pages_configuration("Repo")
    assert RECONCILER._pages_configuration_matches(current, "main") is True
    assert RECONCILER._pages_configuration_matches({}, "main") is False
    assert (
        RECONCILER._pages_configuration_matches(
            {"source": {"branch": "develop", "path": "/docs"}}, "main"
        )
        is False
    )
    assert (
        RECONCILER._pages_configuration_matches(
            {"source": {"branch": "main", "path": "/"}}, "main"
        )
        is False
    )
    assert (
        RECONCILER._pages_configuration_matches(
            {
                "build_type": "workflow",
                "source": {"branch": "main", "path": "/docs"},
            },
            "main",
        )
        is False
    )
    monkeypatch.setattr(RECONCILER, "_gh_api", lambda *args, **kwargs: "[]")
    with pytest.raises(RECONCILER.ManifestError, match="Pages configuration"):
        RECONCILER._pages_configuration("Repo")


def test_deepwiki_requires_one_linked_badge(monkeypatch) -> None:
    """Disconnected, wrong-case, and wrong-target DeepWiki badges are rejected."""

    target = f"https://deepwiki.com/{RECONCILER.ORGANIZATION}/Repo"
    image = "https://deepwiki.com/badge.svg"
    assert RECONCILER._deepwiki_badge_linked(
        f"[![Ask DeepWiki]({image})]({target})", "Repo"
    )
    assert RECONCILER._deepwiki_badge_linked(
        f'<A CLASS="x" HREF="{target}"><IMG ALT="Ask" SRC="{image}"></A>',
        "Repo",
    )
    assert not RECONCILER._deepwiki_badge_linked(
        f'<a href="https://deepwiki.com/contextualwisdomlab/Repo">'
        f'<img src="{image}"></a>',
        "Repo",
    )
    assert not RECONCILER._deepwiki_badge_linked(f"{image}\n{target}", "Repo")
    assert not RECONCILER._deepwiki_badge_linked(
        f"[![Ask]({image})]"
        f"(https://deepwiki.com/{RECONCILER.ORGANIZATION}/Other)",
        "Repo",
    )
    assert not RECONCILER._deepwiki_badge_linked(
        f'<a href="{target}">DeepWiki</a><img src="{image}">',
        "Repo",
    )
    assert not RECONCILER._deepwiki_badge_linked(
        f'<a href="{target}">DeepWiki</a>'
        f'<a href="https://example.com"><img src="{image}"></a>',
        "Repo",
    )

    responses = iter(
        [
            completed(out=f"[![Ask]({image})]({target})"),
            completed(code=1, err="HTTP 404"),
            completed(code=1, err="boom"),
        ]
    )
    monkeypatch.setattr(
        RECONCILER.subprocess, "run", lambda *args, **kwargs: next(responses)
    )
    assert RECONCILER._deepwiki_badge_exists("Repo", "main") is True
    assert RECONCILER._deepwiki_badge_exists("Repo", "main") is False
    with pytest.raises(RuntimeError, match="README state"):
        RECONCILER._deepwiki_badge_exists("Repo", "main")


def test_reconcile_preconditions(monkeypatch) -> None:
    """Public-surface prerequisites block writes only for their own repository."""

    monkeypatch.setattr(
        RECONCILER,
        "_gh_api",
        lambda method, endpoint, **kwargs: (
            json.dumps({"default_branch": "main"}) if method == "GET" else ""
        ),
    )
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    with pytest.raises(RuntimeError, match="DeepWiki badge requested"):
        RECONCILER.reconcile_repository("Repo", desired(deepwiki=True))

    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: True)
    with pytest.raises(RuntimeError, match="DeepWiki badge is disabled"):
        RECONCILER.reconcile_repository("Repo", desired())

    monkeypatch.setattr(RECONCILER, "_docs_index_exists", lambda *args: False)
    with pytest.raises(RuntimeError, match="Pages requested"):
        RECONCILER.reconcile_repository("Repo", desired(deepwiki=True, pages=True))

    monkeypatch.setattr(
        RECONCILER,
        "_gh_api",
        lambda *args, **kwargs: json.dumps({"default_branch": None}),
    )
    with pytest.raises(RuntimeError, match="default branch"):
        RECONCILER.reconcile_repository("Repo", desired())


def test_reconcile_mutation_matrix(monkeypatch) -> None:
    """Descriptions, topics, Pages create/update/disable all reconcile."""

    calls = []

    def gh_api(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if method == "GET" and endpoint.endswith("/topics"):
            return json.dumps({"names": ["old"]})
        if method == "GET" and endpoint.endswith("/pages"):
            return json.dumps(
                {"build_type": "workflow", "source": {"branch": "main", "path": "/"}}
            )
        if method == "GET":
            return json.dumps({"default_branch": "main", "description": "old"})
        return ""

    monkeypatch.setattr(RECONCILER, "_gh_api", gh_api)
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: True)
    monkeypatch.setattr(RECONCILER, "_docs_index_exists", lambda *args: True)
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: False)
    RECONCILER.reconcile_repository(
        "Repo",
        desired(
            description="new",
            topics=["new"],
            deepwiki=True,
            pages=True,
        ),
    )
    assert any(call[0] == "PATCH" for call in calls)
    assert any(call[0] == "PUT" and call[1].endswith("/topics") for call in calls)
    assert any(call[0] == "POST" and call[1].endswith("/pages") for call in calls)

    calls.clear()
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: True)
    RECONCILER.reconcile_repository(
        "Repo", desired(description="new", topics=["new"], deepwiki=True, pages=True)
    )
    assert any(call[0] == "PUT" and call[1].endswith("/pages") for call in calls)

    calls.clear()
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    RECONCILER.reconcile_repository(
        "Repo", desired(description="new", topics=["new"], pages=False)
    )
    assert any(call[0] == "DELETE" and call[1].endswith("/pages") for call in calls)


def test_reconcile_noops_when_already_desired(monkeypatch) -> None:
    """Already-converged repository and Pages state cause no writes."""

    calls = []

    def gh_api(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs))
        if endpoint.endswith("/topics"):
            return json.dumps({"names": ["python"]})
        if endpoint.endswith("/pages"):
            return json.dumps(
                {
                    "build_type": "legacy",
                    "source": {"branch": "main", "path": "/docs"},
                }
            )
        return json.dumps(
            {"default_branch": "main", "description": "Useful product."}
        )

    monkeypatch.setattr(RECONCILER, "_gh_api", gh_api)
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: False)
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: False)
    RECONCILER.reconcile_repository("Repo", desired())
    assert [call[0] for call in calls] == ["GET", "GET"]

    calls.clear()
    monkeypatch.setattr(RECONCILER, "_deepwiki_badge_exists", lambda *args: True)
    monkeypatch.setattr(RECONCILER, "_docs_index_exists", lambda *args: True)
    monkeypatch.setattr(RECONCILER, "_pages_exists", lambda *args: True)
    RECONCILER.reconcile_repository("Repo", desired(deepwiki=True, pages=True))
    assert [call[0] for call in calls] == ["GET", "GET", "GET"]


def test_parse_args(monkeypatch, tmp_path) -> None:
    """CLI supports validation and narrow repository selection."""

    path = tmp_path / "m.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "prog",
            "--manifest",
            str(path),
            "--validate-only",
            "--repository",
            "Repo",
        ],
    )
    args = RECONCILER.parse_args()
    assert args.manifest == path
    assert args.validate_only is True
    assert args.repository == ["Repo"]


def test_main_modes_and_failure_aggregation(monkeypatch, tmp_path, capsys) -> None:
    """Apply mode requires authority and continues siblings before aggregating errors."""

    path = write_manifest(tmp_path, {"A": desired(), "B": desired()})
    monkeypatch.setattr(
        RECONCILER,
        "parse_args",
        lambda: argparse.Namespace(manifest=path, validate_only=True, repository=[]),
    )
    assert RECONCILER.main() == 0

    monkeypatch.setattr(
        RECONCILER,
        "parse_args",
        lambda: argparse.Namespace(manifest=path, validate_only=False, repository=[]),
    )
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN"):
        RECONCILER.main()

    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(
        RECONCILER,
        "parse_args",
        lambda: argparse.Namespace(
            manifest=path,
            validate_only=False,
            repository=["Missing"],
        ),
    )
    with pytest.raises(RECONCILER.ManifestError, match="undeclared"):
        RECONCILER.main()

    monkeypatch.setattr(
        RECONCILER,
        "parse_args",
        lambda: argparse.Namespace(manifest=path, validate_only=False, repository=[]),
    )
    seen = []

    def reconcile(repository, state):
        seen.append(repository)
        if repository == "A":
            raise RuntimeError("boom")

    monkeypatch.setattr(RECONCILER, "reconcile_repository", reconcile)
    with pytest.raises(RuntimeError, match="A: boom"):
        RECONCILER.main()
    assert seen == ["A", "B"]
    assert "failed for A" in capsys.readouterr().err

    monkeypatch.setattr(RECONCILER, "reconcile_repository", lambda *args: None)
    assert RECONCILER.main() == 0


def test_main_catches_supported_errors(monkeypatch, tmp_path) -> None:
    """Expected per-repository runtime failures are aggregated consistently."""

    path = write_manifest(tmp_path)
    monkeypatch.setenv("GH_TOKEN", "x")
    monkeypatch.setattr(
        RECONCILER,
        "parse_args",
        lambda: argparse.Namespace(manifest=path, validate_only=False, repository=[]),
    )
    exceptions = [
        RECONCILER.ManifestError("x"),
        json.JSONDecodeError("x", "x", 0),
        subprocess.TimeoutExpired("gh", 1),
    ]
    for exception in exceptions:
        monkeypatch.setattr(
            RECONCILER,
            "reconcile_repository",
            lambda *args, exception=exception: (_ for _ in ()).throw(exception),
        )
        with pytest.raises(RuntimeError, match="metadata reconciliation failed"):
            RECONCILER.main()


def test_module_main_guard(monkeypatch, tmp_path) -> None:
    """The executable entry point exits successfully for validation mode."""

    path = write_manifest(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--manifest", str(path), "--validate-only"],
    )
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exc.value.code == 0