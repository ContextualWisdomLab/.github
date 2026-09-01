import json
from pathlib import Path
import sys

import pytest

from scripts.ci import repository_metadata_reconciler as reconciler


def _manifest():
    return {
        "schema_version": 1,
        "organization": "ContextualWisdomLab",
        "repositories": {
            "CalendarWeave": {
                "description": "Calendar resource infrastructure for iCalendar, CalDAV, revisions, and interoperable scheduling.",
                "topics": ["calendar", "caldav", "icalendar", "rust", "scheduling"],
                "deepwiki": True,
                "pages": {"enabled": False},
            },
            "ConceptWeave": {
                "description": "Evidence-bound ontology and semantic-model engineering for governed enterprise meaning.",
                "topics": ["ontology", "semantic-model", "knowledge-graph", "rust", "governance"],
                "deepwiki": True,
                "pages": {"enabled": False},
            },
        },
    }


def test_validate_manifest_accepts_exact_casing_and_normalized_topics():
    manifest = reconciler.validate_manifest(_manifest())
    assert manifest["organization"] == "ContextualWisdomLab"
    assert list(manifest["repositories"]) == ["CalendarWeave", "ConceptWeave"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda m: m.update(schema_version=2), "schema_version"),
        (lambda m: m.update(organization="contextualwisdomlab"), "organization"),
        (lambda m: m["repositories"]["CalendarWeave"].update(description="Do not embed this in #74."), "customer-facing"),
        (lambda m: m["repositories"]["CalendarWeave"].update(description=""), "description"),
        (lambda m: m["repositories"]["CalendarWeave"].update(topics=["Calendar"]), "topic"),
        (lambda m: m["repositories"]["CalendarWeave"].update(topics=["calendar", "calendar"]), "duplicate"),
        (lambda m: m["repositories"]["CalendarWeave"].update(deepwiki="yes"), "deepwiki"),
        (lambda m: m["repositories"]["CalendarWeave"].update(pages={"enabled": True, "source": {"branch": "main", "path": "/bad"}}), "Pages"),
    ],
)
def test_validate_manifest_rejects_unsafe_desired_state(mutate, message):
    manifest = _manifest()
    mutate(manifest)
    with pytest.raises(ValueError, match=message):
        reconciler.validate_manifest(manifest)


def test_deepwiki_markdown_preserves_repository_casing():
    assert reconciler.deepwiki_markdown("ContextualWisdomLab", "CalendarWeave") == (
        "[![Ask DeepWiki](https://deepwiki.com/badge.svg)]"
        "(https://deepwiki.com/ContextualWisdomLab/CalendarWeave)"
    )


def test_description_and_topics_operations_are_minimal():
    desired = _manifest()["repositories"]["CalendarWeave"]
    live = {
        "description": "Old internal description. Do not use.",
        "homepage": None,
        "topics": ["calendar", "old-topic"],
        "has_pages": False,
    }
    operations = reconciler.plan_operations("CalendarWeave", live, desired)
    assert operations == [
        ("repository", {"description": desired["description"]}),
        ("topics", {"names": desired["topics"]}),
    ]


def test_plan_pages_create_and_update_only_when_enabled():
    desired = _manifest()["repositories"]["CalendarWeave"] | {
        "pages": {"enabled": True, "source": {"branch": "main", "path": "/docs"}}
    }
    no_pages = {"description": desired["description"], "topics": desired["topics"], "has_pages": False}
    existing_pages = {
        "description": desired["description"],
        "topics": desired["topics"],
        "has_pages": True,
        "pages": {"source": {"branch": "main", "path": "/"}, "build_type": "legacy"},
    }
    assert reconciler.plan_operations("CalendarWeave", no_pages, desired) == [
        ("pages_create", {"build_type": "legacy", "source": {"branch": "main", "path": "/docs"}})
    ]
    assert reconciler.plan_operations("CalendarWeave", existing_pages, desired) == [
        ("pages_update", {"build_type": "legacy", "source": {"branch": "main", "path": "/docs"}})
    ]


class FakeApi:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, payload=None, allow_status=()):
        self.calls.append((method, path, payload, tuple(allow_status)))
        return self.responses.pop(0)


def test_fetch_live_state_reads_repo_topics_and_optional_pages():
    api = FakeApi(
        [
            {"description": "d", "homepage": None, "has_pages": True},
            {"names": ["a"]},
            {"source": {"branch": "main", "path": "/docs"}, "build_type": "legacy"},
        ]
    )
    live = reconciler.fetch_live_state(api, "ContextualWisdomLab", "CalendarWeave")
    assert live["topics"] == ["a"]
    assert live["pages"]["source"]["path"] == "/docs"
    assert api.calls[2][3] == (404,)


def test_fetch_live_state_treats_missing_pages_as_disabled():
    api = FakeApi(
        [
            {"description": "d", "homepage": None, "has_pages": False},
            {"names": []},
            None,
        ]
    )
    live = reconciler.fetch_live_state(api, "ContextualWisdomLab", "CalendarWeave")
    assert live["has_pages"] is False
    assert "pages" not in live


def test_apply_operations_uses_required_rest_methods():
    api = FakeApi([{}, {}, {}, {}])
    ops = [
        ("repository", {"description": "x"}),
        ("topics", {"names": ["a"]}),
        ("pages_create", {"build_type": "legacy", "source": {"branch": "main", "path": "/docs"}}),
        ("pages_update", {"build_type": "legacy", "source": {"branch": "main", "path": "/docs"}}),
    ]
    reconciler.apply_operations(api, "ContextualWisdomLab", "CalendarWeave", ops)
    assert [(c[0], c[1]) for c in api.calls] == [
        ("PATCH", "/repos/ContextualWisdomLab/CalendarWeave"),
        ("PUT", "/repos/ContextualWisdomLab/CalendarWeave/topics"),
        ("POST", "/repos/ContextualWisdomLab/CalendarWeave/pages"),
        ("PUT", "/repos/ContextualWisdomLab/CalendarWeave/pages"),
    ]


def test_cli_audit_requires_no_token(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")

    class AuditApi:
        def request(self, method, path, payload=None, allow_status=()):
            if path.endswith("/topics"):
                return {"names": []}
            if path.endswith("/pages"):
                return None
            return {"description": "stale", "homepage": None, "has_pages": False}

    monkeypatch.setattr(reconciler, "GitHubApi", lambda token=None: AuditApi())
    monkeypatch.delenv("CWL_REPOSITORY_METADATA_TOKEN", raising=False)
    assert reconciler.main(["--manifest", str(path), "--mode", "audit"]) == 0
    output = capsys.readouterr().out
    assert "CalendarWeave" in output
    assert "repository" in output


def test_cli_apply_fails_closed_without_dedicated_token(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(_manifest()), encoding="utf-8")
    monkeypatch.delenv("CWL_REPOSITORY_METADATA_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CWL_REPOSITORY_METADATA_TOKEN"):
        reconciler.main(["--manifest", str(path), "--mode", "apply"])


def test_more_manifest_validation_and_homepage_paths():
    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["description"] = "x" * 351
    with pytest.raises(ValueError, match="customer-facing"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["description"] = "line1\nline2"
    with pytest.raises(ValueError, match="customer-facing"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["topics"] = []
    with pytest.raises(ValueError, match="topic list"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["topics"] = [f"t{i}" for i in range(21)]
    with pytest.raises(ValueError, match="exceeds"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["pages"] = "no"
    with pytest.raises(ValueError, match="Pages"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"] = {}
    with pytest.raises(ValueError, match="repositories"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["Bad/Repo"] = manifest["repositories"].pop("CalendarWeave")
    with pytest.raises(ValueError, match="repository names"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"] = "bad"
    with pytest.raises(ValueError, match="desired state"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["homepage"] = 3
    with pytest.raises(ValueError, match="homepage"):
        reconciler.validate_manifest(manifest)

    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["homepage"] = "https://example.test/"
    validated = reconciler.validate_manifest(manifest)
    assert validated["repositories"]["CalendarWeave"]["homepage"] == "https://example.test/"


def test_homepage_operation_is_planned_when_declared():
    desired = _manifest()["repositories"]["CalendarWeave"] | {"homepage": "https://example.test/"}
    live = {
        "description": desired["description"],
        "homepage": None,
        "topics": desired["topics"],
        "has_pages": False,
    }
    assert reconciler.plan_operations("CalendarWeave", live, desired) == [
        ("repository", {"homepage": "https://example.test/"})
    ]


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self._body


def test_github_api_success_payload_authorization_and_empty_body(monkeypatch):
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request, timeout))
        if len(seen) == 1:
            return _FakeResponse(b'{"ok":true}')
        return _FakeResponse(b"")

    monkeypatch.setattr(reconciler.urllib.request, "urlopen", fake_urlopen)
    api = reconciler.GitHubApi("secret")
    assert api.request("PATCH", "/repos/o/r", {"description": "x"}) == {"ok": True}
    assert api.request("GET", "/repos/o/r") == {}
    first_request = seen[0][0]
    assert first_request.get_header("Authorization") == "Bearer secret"
    assert first_request.data == b'{"description":"x"}'
    assert seen[0][1] == 30


def test_github_api_http_and_transport_failures(monkeypatch):
    import io
    import urllib.error

    api = reconciler.GitHubApi()

    def missing(*args, **kwargs):
        raise urllib.error.HTTPError("u", 404, "missing", {}, io.BytesIO(b""))

    monkeypatch.setattr(reconciler.urllib.request, "urlopen", missing)
    assert api.request("GET", "/repos/o/r/pages", allow_status=(404,)) is None
    with pytest.raises(RuntimeError, match="HTTP 404"):
        api.request("GET", "/repos/o/r")

    def transport(*args, **kwargs):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(reconciler.urllib.request, "urlopen", transport)
    with pytest.raises(RuntimeError, match="transport failure"):
        api.request("GET", "/repos/o/r")


def test_apply_operations_rejects_unknown_operation():
    api = FakeApi([])
    with pytest.raises(ValueError, match="unknown operation"):
        reconciler.apply_operations(api, "ContextualWisdomLab", "CalendarWeave", [("bad", {})])


def test_cli_apply_executes_operations_with_dedicated_token(tmp_path, monkeypatch, capsys):
    path = tmp_path / "manifest.json"
    manifest = _manifest()
    manifest["repositories"] = {"CalendarWeave": manifest["repositories"]["CalendarWeave"]}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    calls = []

    class ApplyApi:
        def __init__(self, token=None):
            assert token == "metadata-token"

        def request(self, method, request_path, payload=None, allow_status=()):
            calls.append((method, request_path, payload))
            if method == "GET" and request_path.endswith("/topics"):
                return {"names": []}
            if method == "GET" and request_path.endswith("/pages"):
                return None
            if method == "GET":
                return {"description": "stale", "homepage": None, "has_pages": False}
            return {}

    monkeypatch.setenv("CWL_REPOSITORY_METADATA_TOKEN", "metadata-token")
    monkeypatch.setattr(reconciler, "GitHubApi", ApplyApi)
    assert reconciler.main(["--manifest", str(path), "--mode", "apply"]) == 0
    assert ("PATCH", "/repos/ContextualWisdomLab/CalendarWeave", {"description": manifest["repositories"]["CalendarWeave"]["description"]}) in calls
    assert ("PUT", "/repos/ContextualWisdomLab/CalendarWeave/topics", {"names": manifest["repositories"]["CalendarWeave"]["topics"]}) in calls
    assert "CalendarWeave" in capsys.readouterr().out


def test_main_guard_executes_audit_path(tmp_path, monkeypatch):
    import runpy

    path = tmp_path / "manifest.json"
    manifest = _manifest()
    manifest["repositories"] = {"CalendarWeave": manifest["repositories"]["CalendarWeave"]}
    path.write_text(json.dumps(manifest), encoding="utf-8")

    responses = iter([
        _FakeResponse(b'{"description":"stale","homepage":null,"has_pages":false}'),
        _FakeResponse(b'{"names":[]}'),
    ])

    def fake_urlopen(request, timeout):
        if request.full_url.endswith("/pages"):
            import io
            import urllib.error
            raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, io.BytesIO(b""))
        return next(responses)

    monkeypatch.setattr(reconciler.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sys, "argv", [
        "repository_metadata_reconciler.py",
        "--manifest",
        str(path),
        "--mode",
        "audit",
    ])
    with pytest.raises(SystemExit) as exc:
        runpy.run_path(str(Path(reconciler.__file__)), run_name="__main__")
    assert exc.value.code == 0


def test_validate_manifest_accepts_enabled_pages_source():
    manifest = _manifest()
    manifest["repositories"]["CalendarWeave"]["pages"] = {
        "enabled": True,
        "source": {"branch": "main", "path": "/docs"},
    }
    validated = reconciler.validate_manifest(manifest)
    assert validated["repositories"]["CalendarWeave"]["pages"] == {
        "enabled": True,
        "source": {"branch": "main", "path": "/docs"},
    }


def test_plan_pages_is_noop_when_existing_pages_match():
    desired = _manifest()["repositories"]["CalendarWeave"] | {
        "pages": {"enabled": True, "source": {"branch": "main", "path": "/docs"}}
    }
    live = {
        "description": desired["description"],
        "topics": desired["topics"],
        "has_pages": True,
        "pages": {
            "source": {"branch": "main", "path": "/docs"},
            "build_type": "legacy",
        },
    }
    assert reconciler.plan_operations("CalendarWeave", live, desired) == []
