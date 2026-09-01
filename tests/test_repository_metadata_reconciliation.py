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
spec = importlib.util.spec_from_file_location("reconcile_repository_metadata", SCRIPT)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def desired(**overrides):
    data = {"description":"Useful product.","topics":["python"],"deepwiki":False,"pages":False}
    data.update(overrides)
    return data


def write_manifest(tmp_path, repositories=None, **root_overrides):
    payload = {"schema_version":1,"organization":m.ORGANIZATION,"repositories": repositories or {"Repo":desired()}}
    payload.update(root_overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def completed(code=0, out="", err=""):
    return subprocess.CompletedProcess(args=["gh"], returncode=code, stdout=out, stderr=err)


def test_reviewed_manifest_scope_and_surface_intent():
    manifest = Path(__file__).resolve().parents[1] / "config" / "repository-metadata.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    repositories = payload["repositories"]
    expected = {
        "CalendarWeave": ("calendar", "icalendar"),
        "ConceptWeave": ("semantic-model", "ontology"),
        "context-graph-contracts": ("interoperability", "cloudevents"),
        "ThreadWeave": ("rfc5256", "python"),
        "RankWeave": ("information-retrieval", "trec"),
        "fast-mlsirm": ("psychometrics", "rust"),
    }
    assert set(repositories) == set(expected)
    for repository, required_topics in expected.items():
        state = repositories[repository]
        assert state["deepwiki"] is True
        assert state["pages"] is True
        assert all(topic in state["topics"] for topic in required_topics)


def test_require_exact_dict_and_repository_validation():
    assert m._require_exact_dict({}, field="x") == {}
    with pytest.raises(m.ManifestError, match="must be an object"):
        m._require_exact_dict([], field="x")
    valid = desired()
    assert m._validate_repository("Repo", valid) == valid
    for name in [1, "bad name"]:
        with pytest.raises(m.ManifestError, match="exact GitHub-safe casing"):
            m._validate_repository(name, valid)
    with pytest.raises(m.ManifestError, match="contain exactly"):
        m._validate_repository("Repo", {**valid, "extra": True})
    for description in [None, "", "x"*351, "do not publish", "issue #7", "https://example.com"]:
        with pytest.raises(m.ManifestError):
            m._validate_repository("Repo", {**valid, "description":description})
    for topics in [None, [], ["x"]*21, [1], ["Bad_Topic"], ["dup","dup"]]:
        with pytest.raises(m.ManifestError):
            m._validate_repository("Repo", {**valid, "topics":topics})
    for field, value in [("deepwiki", 1), ("pages", "yes")]:
        with pytest.raises(m.ManifestError):
            m._validate_repository("Repo", {**valid, field:value})


def test_load_manifest_contracts(tmp_path):
    path = write_manifest(tmp_path)
    assert list(m.load_manifest(path)) == ["Repo"]
    path.write_text(json.dumps([]), encoding="utf-8")
    with pytest.raises(m.ManifestError, match="manifest must be an object"):
        m.load_manifest(path)
    for payload, message in [
        ({"schema_version":1,"organization":m.ORGANIZATION,"repositories":{},"extra":1}, "unexpected key"),
        ({"schema_version":2,"organization":m.ORGANIZATION,"repositories":{}}, "schema or organization"),
        ({"schema_version":1,"organization":"Other","repositories":{}}, "schema or organization"),
        ({"schema_version":1,"organization":m.ORGANIZATION,"repositories":[]}, "repositories must be an object"),
        ({"schema_version":1,"organization":m.ORGANIZATION,"repositories":{}}, "at least one repository"),
    ]:
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(m.ManifestError, match=message):
            m.load_manifest(path)


def test_gh_api_builds_requests_and_fails_closed(monkeypatch):
    seen=[]
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: seen.append((a,kw)) or completed(out="ok"))
    assert m._gh_api("PATCH", "repos/x/y", fields={"a":"b"}, body={"z":1}) == "ok"
    args, kwargs = seen[0]
    assert args[0][:5] == ["gh","api","--method","PATCH","repos/x/y"]
    assert "--input" in args[0] and "--field" in args[0]
    assert kwargs["input"] == '{"z":1}'
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: completed(code=1))
    with pytest.raises(RuntimeError, match="GitHub API request failed"):
        m._gh_api("GET", "repos/x/y")


def test_pages_and_docs_probes(monkeypatch):
    responses = iter([completed(), completed(code=1, err="HTTP 404"), completed(code=1, err="boom")])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: next(responses))
    assert m._pages_exists("Repo") is True
    assert m._pages_exists("Repo") is False
    with pytest.raises(RuntimeError, match="Pages state"):
        m._pages_exists("Repo")
    responses = iter([completed(), completed(code=1, out="Not Found"), completed(code=1, err="boom")])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: next(responses))
    assert m._docs_index_exists("Repo", "main") is True
    assert m._docs_index_exists("Repo", "main") is False
    with pytest.raises(RuntimeError, match="Pages source state"):
        m._docs_index_exists("Repo", "main")


def test_deepwiki_requires_one_linked_badge(monkeypatch):
    target = f"https://deepwiki.com/{m.ORGANIZATION}/Repo"
    image = "https://deepwiki.com/badge.svg"
    assert m._deepwiki_badge_linked(f"[![Ask DeepWiki]({image})]({target})", "Repo")
    assert m._deepwiki_badge_linked(
        f'<A CLASS="x" HREF="{target}"><IMG ALT="Ask" SRC="{image}"></A>', "Repo"
    )
    assert not m._deepwiki_badge_linked(
        f'<a href="https://deepwiki.com/contextualwisdomlab/Repo"><img src="{image}"></a>',
        "Repo",
    )
    assert not m._deepwiki_badge_linked(f"{image}\n{target}", "Repo")
    assert not m._deepwiki_badge_linked(f"[![Ask]({image})](https://deepwiki.com/{m.ORGANIZATION}/Other)", "Repo")
    responses = iter([
        completed(out=f"[![Ask]({image})]({target})"),
        completed(code=1, err="HTTP 404"),
        completed(code=1, err="boom"),
    ])
    monkeypatch.setattr(m.subprocess, "run", lambda *a, **kw: next(responses))
    assert m._deepwiki_badge_exists("Repo", "main") is True
    assert m._deepwiki_badge_exists("Repo", "main") is False
    with pytest.raises(RuntimeError, match="README state"):
        m._deepwiki_badge_exists("Repo", "main")


def test_reconcile_preconditions(monkeypatch):
    monkeypatch.setattr(m, "_gh_api", lambda method, endpoint, **kw: json.dumps({"default_branch":"main"}) if method=="GET" else "")
    monkeypatch.setattr(m, "_deepwiki_badge_exists", lambda *a: False)
    with pytest.raises(RuntimeError, match="DeepWiki badge requested"):
        m.reconcile_repository("Repo", desired(deepwiki=True))
    monkeypatch.setattr(m, "_deepwiki_badge_exists", lambda *a: True)
    monkeypatch.setattr(m, "_docs_index_exists", lambda *a: False)
    with pytest.raises(RuntimeError, match="Pages requested"):
        m.reconcile_repository("Repo", desired(deepwiki=True, pages=True))
    monkeypatch.setattr(m, "_gh_api", lambda *a, **kw: json.dumps({"default_branch":None}))
    with pytest.raises(RuntimeError, match="default branch"):
        m.reconcile_repository("Repo", desired())


def test_reconcile_mutation_matrix(monkeypatch):
    calls=[]
    def gh(method, endpoint, **kwargs):
        calls.append((method,endpoint,kwargs))
        if method == "GET" and endpoint.endswith("/topics"):
            return json.dumps({"names":["old"]})
        if method == "GET":
            return json.dumps({"default_branch":"main","description":"old"})
        return ""
    monkeypatch.setattr(m, "_gh_api", gh)
    monkeypatch.setattr(m, "_deepwiki_badge_exists", lambda *a: True)
    monkeypatch.setattr(m, "_docs_index_exists", lambda *a: True)
    monkeypatch.setattr(m, "_pages_exists", lambda *a: False)
    m.reconcile_repository("Repo", desired(description="new", topics=["new"], deepwiki=True, pages=True))
    assert any(c[0]=="PATCH" for c in calls)
    assert any(c[0]=="PUT" and c[1].endswith("/topics") for c in calls)
    assert any(c[0]=="POST" and c[1].endswith("/pages") for c in calls)
    calls.clear()
    monkeypatch.setattr(m, "_pages_exists", lambda *a: True)
    m.reconcile_repository("Repo", desired(description="new", topics=["new"], pages=True))
    assert any(c[0]=="PUT" and c[1].endswith("/pages") for c in calls)
    calls.clear()
    m.reconcile_repository("Repo", desired(description="new", topics=["new"], pages=False))
    assert any(c[0]=="DELETE" and c[1].endswith("/pages") for c in calls)


def test_reconcile_noops_when_already_desired_and_pages_absent(monkeypatch):
    calls=[]
    def gh(method, endpoint, **kwargs):
        calls.append((method,endpoint,kwargs))
        if endpoint.endswith("/topics"):
            return json.dumps({"names":["python"]})
        return json.dumps({"default_branch":"main","description":"Useful product."})
    monkeypatch.setattr(m, "_gh_api", gh)
    monkeypatch.setattr(m, "_pages_exists", lambda *a: False)
    m.reconcile_repository("Repo", desired())
    assert [c[0] for c in calls] == ["GET","GET"]


def test_parse_args(monkeypatch, tmp_path):
    path = tmp_path/"m.json"
    monkeypatch.setattr(sys, "argv", ["prog","--manifest",str(path),"--validate-only","--repository","Repo"])
    args = m.parse_args()
    assert args.manifest == path and args.validate_only and args.repository == ["Repo"]


def test_main_modes_and_failure_aggregation(monkeypatch, tmp_path, capsys):
    path = write_manifest(tmp_path, {"A":desired(), "B":desired()})
    monkeypatch.setattr(m, "parse_args", lambda: argparse.Namespace(manifest=path, validate_only=True, repository=[]))
    assert m.main() == 0
    monkeypatch.setattr(m, "parse_args", lambda: argparse.Namespace(manifest=path, validate_only=False, repository=[]))
    monkeypatch.delenv("GH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="GH_TOKEN"):
        m.main()
    monkeypatch.setenv("GH_TOKEN","x")
    monkeypatch.setattr(m, "parse_args", lambda: argparse.Namespace(manifest=path, validate_only=False, repository=["Missing"]))
    with pytest.raises(m.ManifestError, match="undeclared"):
        m.main()
    monkeypatch.setattr(m, "parse_args", lambda: argparse.Namespace(manifest=path, validate_only=False, repository=[]))
    seen=[]
    def reconcile(repo, state):
        seen.append(repo)
        if repo == "A":
            raise RuntimeError("boom")
    monkeypatch.setattr(m, "reconcile_repository", reconcile)
    with pytest.raises(RuntimeError, match="A: boom"):
        m.main()
    assert seen == ["A","B"]
    assert "failed for A" in capsys.readouterr().err
    monkeypatch.setattr(m, "reconcile_repository", lambda *a: None)
    assert m.main() == 0


def test_main_catches_supported_errors(monkeypatch, tmp_path):
    path = write_manifest(tmp_path)
    monkeypatch.setenv("GH_TOKEN","x")
    monkeypatch.setattr(m, "parse_args", lambda: argparse.Namespace(manifest=path, validate_only=False, repository=[]))
    for exc in [m.ManifestError("x"), json.JSONDecodeError("x","x",0), subprocess.TimeoutExpired("gh", 1)]:
        monkeypatch.setattr(m, "reconcile_repository", lambda *a, exc=exc: (_ for _ in ()).throw(exc))
        with pytest.raises(RuntimeError, match="metadata reconciliation failed"):
            m.main()


def test_module_main_guard(monkeypatch, tmp_path):
    path = write_manifest(tmp_path)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), "--manifest", str(path), "--validate-only"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert exc.value.code == 0
