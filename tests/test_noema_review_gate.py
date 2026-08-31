import base64
import json
import sys
from pathlib import Path

import pytest

from scripts.ci import noema_review_gate as noema


def fake_secret(*parts: str) -> str:
    return "".join(parts)


def make_pr(**overrides):
    """Build a minimal pull request payload for Noema tests."""
    value = {
        "number": 7,
        "title": "Noema",
        "body": "",
        "isDraft": False,
        "state": "OPEN",
        "headRefOid": "head",
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": []}},
    }
    value.update(overrides)
    return value


def review(state="APPROVED", commit="head", login="opencode-agent", body="Result: APPROVE"):
    """Build a minimal review node for Noema tests."""
    return {
        "state": state,
        "body": body,
        "author": {"login": login},
        "commit": {"oid": commit},
    }


def test_run_split_repo_graphql_and_fetch_pr(monkeypatch):
    assert noema.run([sys.executable, "-c", "print('ok')"]).strip() == "ok"
    with pytest.raises(TypeError):
        noema.run("echo unsafe")  # type: ignore[arg-type]
    with pytest.raises(RuntimeError):
        noema.run([sys.executable, "-c", "import sys; sys.exit(5)"])

    assert noema.split_repo("owner/repo") == ("owner", "repo")

def test_scrub_sensitive_data():
    assert noema.scrub_sensitive_data(None) is None
    assert noema.scrub_sensitive_data("") == ""
    assert noema.scrub_sensitive_data("ok") == "ok"
    assert noema.scrub_sensitive_data("Bearer abcdef123") == "Bearer ***"
    assert noema.scrub_sensitive_data("TOKEN xyz_987") == "TOKEN ***"
    assert noema.scrub_sensitive_data(fake_secret("github_", "pat_", "123456789")) == "***"
    assert noema.scrub_sensitive_data(fake_secret("gh", "p_", "12345")) == "***"
    assert noema.scrub_sensitive_data("sk-abc-123_456") == "***"
    assert noema.scrub_sensitive_data("xoxb-1234-5678") == "***"
    assert noema.scrub_sensitive_data("AKIA1234567890ABCDEF") == "***"
    assert noema.scrub_sensitive_data("api_key=12345") == "api_key=***"
    assert noema.scrub_sensitive_data("client_secret='abc'") == "client_secret=***"
    assert noema.scrub_sensitive_data("password: xyz") == "password: ***"


def test_scrub_sensitive_data_authorization_headers():
    assert noema.scrub_sensitive_data("Authorization: Basic dXNlcjpwYXNz") == "Authorization: Basic ***"
    assert noema.scrub_sensitive_data("Proxy-Authorization: Basic dXNlcjpwYXNz") == "Proxy-Authorization: Basic ***"
    assert noema.scrub_sensitive_data("authorization: bearer xyz") == "authorization: bearer ***"


def test_split_repo_and_graphql(monkeypatch):
    with pytest.raises(ValueError):
        noema.split_repo("owner")
    with pytest.raises(ValueError):
        noema.split_repo("/repo")

    calls = []

    def fake_run(args, stdin=None):
        calls.append((args, stdin))
        return '{"data":{"repository":{"pullRequest":{"number":7}}}}'

    monkeypatch.setattr(noema, "run", fake_run)
    assert noema.graphql("query", owner="owner", number=7)["data"]["repository"]["pullRequest"]["number"] == 7
    assert "-f" in calls[0][0]
    assert "-F" in calls[0][0]
    assert noema.fetch_pr("owner/repo", 7) == {"number": 7}

    monkeypatch.setattr(noema, "graphql", lambda *args, **kwargs: {"data": {"repository": {"pullRequest": None}}})
    with pytest.raises(RuntimeError, match="was not found"):
        noema.fetch_pr("owner/repo", 8)


def test_existing_noema_review_matches_actor_and_head():
    noema_marker = "<!-- noema-review-gate head_sha=head -->"
    assert noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="noema", body=noema_marker)]}),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="human", body=noema_marker)]}),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="noema", body="review without gate marker")]}),
        "noema",
    )
    assert not noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="", body=noema_marker)]}),
        "",
    )
    assert not noema.existing_noema_review(make_pr(reviews={"nodes": [review("DISMISSED", login="noema")]}), "noema")
    assert not noema.existing_noema_review(make_pr(reviews={"nodes": [review(commit="old", login="noema")]}), "noema")


def test_require_expected_head_rejects_invalid_closed_and_stale_targets():
    head = "a" * 40
    noema.require_expected_head(make_pr(headRefOid=head), head)
    noema.require_expected_head(make_pr(headRefOid=head), head.upper())
    with pytest.raises(RuntimeError, match="full commit SHA"):
        noema.require_expected_head(make_pr(headRefOid=head), "short")
    with pytest.raises(RuntimeError, match="closed or its head changed"):
        noema.require_expected_head(make_pr(headRefOid=head, state="CLOSED"), head)
    with pytest.raises(RuntimeError, match="closed or its head changed"):
        noema.require_expected_head(make_pr(headRefOid="b" * 40), head)


def test_current_actor_fetch_diff_and_json_extraction(monkeypatch):
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", "cwl-noema-review[bot]")
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", "123")
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "noema-review-github-app")
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API not needed")))
    assert noema.current_actor() == "cwl-noema-review[bot]"

    monkeypatch.delenv("NOEMA_REVIEW_ACTOR")
    monkeypatch.delenv("NOEMA_REVIEW_INSTALLATION_ID")
    monkeypatch.delenv("NOEMA_REVIEW_TOKEN_SOURCE")
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "noema\n")
    assert noema.current_actor() == "noema"
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no gh")))
    assert noema.current_actor() == ""

    def app_identity(args, **kwargs):
        if args[2] == "user":
            return ""
        return "cwl-noema-review\n"

    monkeypatch.setattr(noema, "run", app_identity)
    assert noema.current_actor() == "cwl-noema-review[bot]"

    source = "complete\n" + "x" * (noema.MAX_DIFF_CHARS + 5)
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: source)
    diff, truncated = noema.fetch_diff("owner/repo", 1)
    assert truncated
    assert diff == "complete"

    source = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -0,0 +1 @@\n+" + "x" * noema.MAX_DIFF_CHARS
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: source)
    diff, truncated = noema.fetch_diff("owner/repo", 1)
    assert truncated
    assert diff.endswith("+[overlong changed line content omitted]")
    assert ("a.py", 1, "RIGHT") in noema.changed_diff_locations(diff)
    assert len(diff) <= noema.MAX_DIFF_CHARS

    assert noema.extract_json_object('{"decision":"approve"}') == {"decision": "approve"}
    assert noema.extract_json_object('prefix {"decision":"comment"} suffix') == {"decision": "comment"}
    with pytest.raises(RuntimeError, match="did not contain"):
        noema.extract_json_object("not-json")


@pytest.mark.parametrize(
    ("actor", "installation_id", "source"),
    [
        ("opencode-agent[bot]", "123", "noema-review-pat"),
        ("not a bot", "123", "noema-review-github-app"),
        ("cwl-noema-review[bot]", "not-numeric", "noema-review-github-app"),
    ],
)
def test_current_actor_rejects_unbound_action_identity(monkeypatch, actor, installation_id, source):
    monkeypatch.setenv("NOEMA_REVIEW_ACTOR", actor)
    monkeypatch.setenv("NOEMA_REVIEW_INSTALLATION_ID", installation_id)
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", source)
    with pytest.raises(RuntimeError, match="identity binding is invalid"):
        noema.current_actor()


def test_review_context_builders_include_codegraph_threads_and_files(monkeypatch, tmp_path):
    assert noema.truncate_text("abc", 10) == "abc"
    assert "truncated 2 characters" in noema.truncate_text("abcdef", 4)
    assert "missing PR head SHA" in noema.changed_file_context("owner/repo", 7, "")

    original_fetch_paths = noema.fetch_changed_file_paths
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: [])
    assert "no changed files" in noema.changed_file_context("owner/repo", 7, "head")
    monkeypatch.setattr(noema, "fetch_changed_file_paths", original_fetch_paths)

    encoded = base64.b64encode(b"print('hello')\n").decode("ascii")
    calls = []

    def fake_run(args, stdin=None):
        calls.append(args)
        target = args[2]
        if target.endswith("/files"):
            return "src/a.py\nREADME.md\nempty.txt\n"
        if "contents/src/a.py" in target:
            return encoded
        if "contents/README.md" in target:
            raise RuntimeError("Command failed: token secret")
        if "contents/empty.txt" in target:
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(noema, "run", fake_run)
    codegraph_path = tmp_path / "codegraph.md"
    codegraph_path.write_text("call graph: src/a.py -> tests", encoding="utf-8")
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(codegraph_path))
    pr = make_pr(
        headRefOid="head sha",
        reviewThreads={
            "nodes": [
                {
                    "isResolved": False,
                    "isOutdated": False,
                    "path": "src/a.py",
                    "line": 3,
                    "comments": {"nodes": [{"author": {"login": "reviewer"}, "body": "check call site"}]},
                },
                {
                    "isResolved": True,
                    "isOutdated": False,
                    "path": "README.md",
                    "comments": {"nodes": []},
                },
            ]
        },
    )

    context = noema.build_review_context("owner/repo", 7, pr)

    assert "## CodeGraph context" in context
    assert "call graph: src/a.py -> tests" in context
    assert "Thread open at src/a.py:3" in context
    assert "reviewer: check call site" in context
    assert "### src/a.py" in context
    assert "print('hello')" in context
    assert "Unavailable from head content API" in context
    assert "No UTF-8 text content available" in context
    assert any("/files" in call[2] for call in calls)


def test_review_context_reports_omitted_files_and_missing_codegraph(monkeypatch, tmp_path):
    monkeypatch.delenv("NOEMA_CODEGRAPH_CONTEXT_PATH", raising=False)
    assert noema.load_codegraph_context() == ""

    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(tmp_path / "missing.md"))
    assert "CodeGraph context unavailable" in noema.load_codegraph_context()

    paths = [f"src/file_{index}.py" for index in range(noema.MAX_CONTEXT_FILES + 1)]
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)
    monkeypatch.setattr(noema, "fetch_head_file_content", lambda repo, path, head_sha: "x")

    context = noema.changed_file_context("owner/repo", 7, "head")

    assert "1 changed files omitted from context budget" in context


class FakeResponse:
    """Small context-manager response for urllib monkeypatches."""

    def __init__(self, payload):
        """Store a JSON-serializable response payload."""
        self.payload = payload

    def __enter__(self):
        """Return the response for with-statement use."""
        return self

    def __exit__(self, *args):
        """Propagate exceptions from the with-statement body."""
        return False

    def read(self):
        """Return the payload as encoded JSON bytes."""
        return json.dumps(self.payload).encode("utf-8")


def test_call_llm_handles_configuration_and_verdicts(monkeypatch):
    monkeypatch.setattr(noema, "validate_substantive_verdict", lambda *_args: None)
    pr = make_pr()
    monkeypatch.delenv("NOEMA_LLM_API_URL", raising=False)
    monkeypatch.delenv("NOEMA_LLM_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="not configured"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "file:///etc/passwd")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "review-model")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "decision": "approve",
                                    "summary": "ok",
                                    "findings": [
                                        {"severity": "low", "file": "a.py", "line": 1, "side": "RIGHT", "message": "checked"},
                                        {"severity": "medium", "file": "b.py", "line": 2, "side": "LEFT", "message": "checked"},
                                    ],
                                }
                            )
                        }
                    }
                ]
            }
        )

    # Since we replaced urlopen with build_opener, we mock build_opener
    class FakeOpener:
        def __init__(self, call_func):
            self.call_func = call_func
        def open(self, request, timeout=None):
            return self.call_func(request, timeout)

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    verdict = noema.call_llm("owner/repo", 1, pr, "diff", True, "extra review context")
    assert verdict["decision"] == "approve"
    assert seen["url"] == "https://llm.example.test/chat"
    assert seen["body"]["model"] == "review-model"
    assert "extra review context" in seen["body"]["messages"][1]["content"]

    def fake_urlopen_defer(request, timeout=None):
        return FakeResponse({"choices": [{"message": {"content": '{"decision":"defer"}'}}]})

    monkeypatch.setattr(
        noema.urllib.request,
        "build_opener",
        lambda *args: FakeOpener(fake_urlopen_defer)
    )
    with pytest.raises(RuntimeError, match="unsupported decision"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Test case-insensitive valid URL
    monkeypatch.setenv("NOEMA_LLM_API_URL", "HTTPS://llm.example.test/chat")
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    # Test invalid scheme (and no original URL in error)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "file:///etc/passwd")
    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Test localhost rejection
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://localhost/chat")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Test missing hostname
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http:///chat")
    with pytest.raises(ValueError, match="URL must have a valid hostname"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Test internal IP rejection
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://169.254.169.254/chat")
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    import socket
    original_getaddrinfo = socket.getaddrinfo

    # Test DNS resolution bypass
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://resolved-to-local.example.com/chat")
    def fake_getaddrinfo(host, port, *args, **kwargs):
        if host == "resolved-to-local.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Test unresolved hostname does not break
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://unresolved.example.com/chat")
    def fake_getaddrinfo_error(host, port, *args, **kwargs):
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_error)
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    # Test invalid IP string from getaddrinfo (unlikely but theoretically possible)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://weird-dns.example.com/chat")
    def fake_getaddrinfo_invalid_ip(host, port, *args, **kwargs):
        if host == "weird-dns.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not_an_ip", 0))]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_invalid_ip)
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"


def test_noema_redirect_handler_rejects_redirects():
    """Noema must not follow redirects after validating the initial URL."""
    handler = noema.NoRedirectHandler()
    request = noema.urllib.request.Request("https://llm.example.test/chat")

    with pytest.raises(noema.urllib.error.HTTPError):
        handler.redirect_request(
            request,
            fp=None,
            code=302,
            msg="Found",
            headers={},
            newurl="http://169.254.169.254/latest/meta-data/",
        )


def test_call_llm_rejects_control_character_scheme_evasion(monkeypatch):
    """A URL with an embedded tab is normalized by urlparse to an http scheme
    with a valid hostname, but its raw form does not start with http:// — the
    startswith guard must still reject it to prevent SSRF via control-character
    scheme evasion."""
    pr = make_pr()
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http\t://sneaky.example.com/chat")

    import socket

    def raise_gaierror(host, port, *args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", raise_gaierror)
    with pytest.raises(ValueError, match="must start with http:// or https://"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)


def test_call_llm_rejects_non_http_parsed_scheme(monkeypatch):
    """Keep the parsed-scheme SSRF guard covered as defense in depth."""
    pr = make_pr()
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    parsed = noema.urllib.parse.ParseResult("file", "llm.example.test", "/chat", "", "", "")
    monkeypatch.setattr(noema.urllib.parse, "urlparse", lambda _: parsed)

    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)


def test_format_findings_and_submit_review(monkeypatch):
    findings = noema.format_findings(
        [
            {"severity": "high", "file": "a.py", "line": 3, "side": "RIGHT", "message": "bad"},
            {"severity": "low", "file": "b.py", "line": 0, "message": "note"},
            "skip",
            {"message": ""},
        ]
    )
    assert findings == ["- [high] a.py:3 (RIGHT): bad", "- [low] b.py: note"]

    calls = []
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "oidc")
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: calls.append((args, json.loads(stdin))) or "")
    noema.submit_review(
        "owner/repo",
        7,
        make_pr(),
        "noema",
        {"decision": "request_changes", "summary": "fix it", "findings": [{"file": "a.py", "line": 1, "side": "RIGHT", "message": "bad"}]},
    )
    payload = calls[0][1]
    assert payload["event"] == "REQUEST_CHANGES"
    assert payload["commit_id"] == "head"
    assert "Noema LLM review" in payload["body"]
    assert "oidc" in payload["body"]

    calls.clear()
    noema.submit_review("owner/repo", 7, make_pr(), "", {"decision": "comment"})
    assert calls[0][1]["event"] == "COMMENT"
    assert "No blocking findings" in calls[0][1]["body"]


def test_inspect_and_review_skip_paths(monkeypatch):
    head = "a" * 40
    clean_pr = make_pr(headRefOid=head)
    calls = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok", "findings": []})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7, head) == 0
    assert calls

    cases = [
        (make_pr(headRefOid=head, isDraft=True), "noema"),
        (make_pr(headRefOid=head, reviews={"nodes": [review(commit=head, login="noema", body="<!-- noema-review-gate head_sha=head -->")]}), "noema"),
    ]
    for pr, actor in cases:
        calls.clear()
        monkeypatch.setattr(noema, "fetch_pr", lambda repo, number, pr=pr: pr)
        monkeypatch.setattr(noema, "current_actor", lambda actor=actor: actor)
        assert noema.inspect_and_review("owner/repo", 7, head) == 0
        assert calls == []

    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "")
    with pytest.raises(RuntimeError, match="identity could not be verified"):
        noema.inspect_and_review("owner/repo", 7, head)

    monkeypatch.setattr(noema, "current_actor", lambda: "opencode-agent")
    with pytest.raises(RuntimeError, match="independent reviewer credential"):
        noema.inspect_and_review("owner/repo", 7, head)


def test_inspect_and_review_does_not_wait_for_other_reviews_or_checks(monkeypatch):
    head = "a" * 40
    pr = make_pr(
        headRefOid=head,
        reviews={"nodes": [review("CHANGES_REQUESTED")]},
        reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]},
        statusCheckRollup={"contexts": {"nodes": [{"__typename": "StatusContext", "context": "ci", "state": "FAILURE"}]}},
    )
    calls = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, value: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok"})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7, head) == 0
    assert calls


def test_inspect_and_review_rechecks_head_before_publication(monkeypatch):
    head = "a" * 40
    stale = make_pr(headRefOid="b" * 40)
    responses = iter([make_pr(headRefOid=head), make_pr(headRefOid=head), stale])
    submitted = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: next(responses))
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve"})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: submitted.append(args))

    with pytest.raises(RuntimeError, match="head changed"):
        noema.inspect_and_review("owner/repo", 7, head)
    assert submitted == []


def test_call_llm_rejects_empty_review_content(monkeypatch):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": '{"decision":"approve"}'}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="substantive summary"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False)


@pytest.mark.parametrize("message", [[], {}, 0, "   "])
def test_call_llm_rejects_malformed_blocking_findings(monkeypatch, message):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    verdict = {
        "decision": "request_changes",
        "summary": "blocking issue",
        "findings": [{"severity": "high", "file": "a.py", "line": 1, "side": "RIGHT", "message": message}],
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="malformed finding"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False)


@pytest.mark.parametrize(
    ("findings", "error"),
    [
        (None, "list of objects"),
        ([0], "list of objects"),
        ([{"severity": "info", "file": "a.py", "line": 1, "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": 1, "line": 1, "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": " ", "line": 1, "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": "a.py", "line": "1", "message": "bad"}], "malformed finding"),
        ([{"severity": "high", "file": "a.py", "line": 0, "message": "bad"}], "malformed finding"),
        ([], "substantive finding"),
    ],
)
def test_call_llm_rejects_invalid_findings_contract(monkeypatch, findings, error):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    verdict = {"decision": "request_changes", "summary": "blocking issue", "findings": findings}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match=error):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False)


def test_call_llm_rejects_generic_approve_without_changed_line_evidence(monkeypatch):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    verdict = {"decision": "approve", "summary": "No blocking issues found.", "findings": []}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return json.dumps({"choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()

    monkeypatch.setattr(noema.urllib.request.OpenerDirector, "open", lambda *args, **kwargs: Response())
    with pytest.raises(RuntimeError, match="parseable changed-line evidence"):
        noema.call_llm("owner/repo", 7, make_pr(), "diff", False)


def test_call_llm_repairs_one_rejected_changed_line_verdict(monkeypatch):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    diff = """--- a/tool.py
+++ b/tool.py
@@ -1 +1 @@
-old = True
+new = True
"""
    invalid = {
        "decision": "approve",
        "summary": "Checked the replacement.",
        "findings": [],
        "reviewed_lines": [
            {"path": "tool.py", "line": 2, "side": "RIGHT", "analysis": "Checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Callers were not executed.",
            "probes": [],
        },
    }
    valid = {
        **invalid,
        "reviewed_lines": [
            {"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "Checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Callers were not executed.",
            "probes": [
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The assignment was removed.",
                    "attack_or_counterexample": "Inspect the added hunk line.",
                    "evidence": "The RIGHT-side assignment remains present.",
                    "outcome": "falsified",
                },
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The value became false.",
                    "attack_or_counterexample": "Read the replacement literal.",
                    "evidence": "The literal is True.",
                    "outcome": "falsified",
                },
            ],
        },
    }
    payloads = []

    class Response:
        def __init__(self, verdict):
            self.verdict = verdict

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(self.verdict)}}]}
            ).encode()

    class Opener:
        def open(self, request, timeout=None):
            assert timeout is None
            payloads.append(json.loads(request.data))
            return Response(invalid if len(payloads) == 1 else valid)

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())

    assert noema.call_llm("owner/repo", 7, make_pr(), diff, False)["decision"] == "approve"
    assert len(payloads) == 2
    assert "trusted validator" in payloads[1]["messages"][1]["content"]
    assert (
        '"reviewed_lines":[{"path":"tool.py","line":1,"side":"LEFT"'
        in payloads[1]["messages"][1]["content"]
    )


def test_noema_adr_forbids_fixed_model_inference_timeouts() -> None:
    """Long-running reasoning must not be misclassified as provider failure."""
    adr = Path("docs/adr/0003-contextual-orchestrator-vendored-free-zdr.md").read_text()
    normalized = " ".join(adr.split())

    assert "MUST NOT impose a fixed wall-clock timeout on model inference" in normalized
    assert "initial completion ping" in normalized


def test_substantive_approve_requires_exact_changed_lines_and_falsified_probes():
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1,2 +1,2 @@
-old = True
+new = True
 keep = 1
"""
    verdict = {
        "decision": "approve",
        "summary": "The changed assignment preserves the required invariant.",
        "findings": [],
        "reviewed_lines": [
            {"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "The new assignment is explicit."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Runtime consumers outside this diff were not executed.",
            "probes": [
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The value becomes false.",
                    "attack_or_counterexample": "Trace the literal assigned at the changed line.",
                    "evidence": "The changed source assigns the boolean literal True.",
                    "outcome": "falsified",
                },
                {
                    "path": "tool.py",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The assignment is removed.",
                    "attack_or_counterexample": "Compare the added side with the deleted side.",
                    "evidence": "The RIGHT-side hunk contains one replacement assignment.",
                    "outcome": "falsified",
                },
            ],
        },
    }
    noema.validate_substantive_verdict(verdict, diff)

    verdict["adversarial_validation"]["probes"][0]["outcome"] = "confirmed"
    with pytest.raises(RuntimeError, match="approve cannot contain a confirmed"):
        noema.validate_substantive_verdict(verdict, diff)


def test_substantive_verdict_fail_closed_boundaries():
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1 +1 @@
-old = True
+new = True
"""
    valid = {
        "decision": "approve",
        "summary": "The replacement keeps the invariant.",
        "findings": [],
        "reviewed_lines": [{"path": "tool.py", "line": 1, "side": "RIGHT", "analysis": "The replacement is explicit."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Callers were not executed.",
            "probes": [
                {"path": "tool.py", "line": 1, "side": "RIGHT", "hypothesis": "The value is false.", "attack_or_counterexample": "Read the literal.", "evidence": "The literal is True.", "outcome": "falsified"},
                {"path": "tool.py", "line": 1, "side": "RIGHT", "hypothesis": "The assignment vanished.", "attack_or_counterexample": "Inspect the added line.", "evidence": "One assignment is present.", "outcome": "falsified"},
            ],
        },
    }

    assert noema.validate_substantive_verdict({"decision": "comment"}, diff) is None
    invalid_cases = [
        (lambda value: value.pop("reviewed_lines"), "at least one reviewed"),
        (lambda value: value.update(reviewed_lines=[None]), "reviewed line 1 must be an object"),
        (lambda value: value["reviewed_lines"][0].update(analysis=""), "requires concrete analysis"),
        (lambda value: value.pop("adversarial_validation"), "requires adversarial_validation"),
        (lambda value: value["adversarial_validation"].update(status="failed"), "status=passed"),
        (lambda value: value["adversarial_validation"].update(residual_risk=""), "requires residual_risk"),
        (lambda value: value["adversarial_validation"].update(probes=[]), "at least 2 concrete probe"),
        (lambda value: value["adversarial_validation"].update(probes=[None, None]), "probe 1 must be an object"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(line=2), "not an exact changed-side line"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(hypothesis=""), "requires hypothesis"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(attack_or_counterexample=""), "requires attack_or_counterexample"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(evidence=""), "requires evidence"),
        (lambda value: value["adversarial_validation"]["probes"][0].update(outcome="unknown"), "outcome must be"),
        (lambda value: value["adversarial_validation"]["probes"].__setitem__(1, dict(value["adversarial_validation"]["probes"][0])), "duplicates an earlier probe"),
    ]
    for mutate, message in invalid_cases:
        candidate = json.loads(json.dumps(valid))
        mutate(candidate)
        with pytest.raises(RuntimeError, match=message):
            noema.validate_substantive_verdict(candidate, diff)


def test_changed_diff_locations_handles_new_files_and_no_newline_marker():
    diff = """diff --git a/new.py b/new.py
--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
+enabled = True
\\ No newline at end of file
"""
    assert noema.changed_diff_locations(diff) == {("new.py", 1, "RIGHT")}
    malformed_side_lines = """--- /dev/null
+++ b/new.py
@@ -0,0 +1 @@
-impossible deletion
--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
+impossible addition
"""
    assert noema.changed_diff_locations(malformed_side_lines) == set()
    impossible_addition = """--- a/old.py
+++ /dev/null
@@ -1 +0,0 @@
+impossible addition
"""
    assert noema.changed_diff_locations(impossible_addition) == set()


def test_changed_diff_locations_decodes_git_quoted_utf8_paths():
    diff = '''diff --git "a/caf\\303\\251.py" "b/caf\\303\\251.py"
--- "a/caf\\303\\251.py"
+++ "b/caf\\303\\251.py"
@@ -1 +1 @@
-old = True
+new = True
'''
    assert noema.changed_diff_locations(diff) == {
        ("café.py", 1, "LEFT"),
        ("café.py", 1, "RIGHT"),
    }
    assert noema.parse_diff_path('"unterminated', "a/") == ""


def test_changed_diff_locations_keeps_diff_like_hunk_content():
    diff = """diff --git a/tool.py b/tool.py
--- a/tool.py
+++ b/tool.py
@@ -1,2 +1,2 @@
---deleted content
-old tail
+++added content
+new tail
"""
    assert noema.changed_diff_locations(diff) == {
        ("tool.py", 1, "LEFT"),
        ("tool.py", 2, "LEFT"),
        ("tool.py", 1, "RIGHT"),
        ("tool.py", 2, "RIGHT"),
    }


def test_complete_changed_paths_preserve_material_probe_requirement():
    diff = """--- a/docs/note.md
+++ b/docs/note.md
@@ -1 +1 @@
-old
+new
"""
    verdict = {
        "decision": "approve",
        "summary": "Documentation remains accurate.",
        "findings": [],
        "reviewed_lines": [
            {"path": "docs/note.md", "line": 1, "side": "RIGHT", "analysis": "Replacement checked."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "Runtime file was outside the prompt diff.",
            "probes": [
                {
                    "path": "docs/note.md",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The replacement is empty.",
                    "attack_or_counterexample": "Inspect the added line.",
                    "evidence": "The added line is nonempty.",
                    "outcome": "falsified",
                }
            ],
        },
    }
    with pytest.raises(RuntimeError, match="at least 2 concrete probe"):
        noema.validate_substantive_verdict(
            verdict, diff, ["docs/note.md", "src/runtime.py"]
        )


def test_substantive_verdict_rejects_non_changed_location_and_accepts_left_deletion():
    diff = """diff --git a/docs/old.md b/docs/old.md
--- a/docs/old.md
+++ /dev/null
@@ -3 +0,0 @@
-obsolete claim
"""
    verdict = {
        "decision": "approve",
        "summary": "The obsolete claim is removed.",
        "findings": [],
        "reviewed_lines": [
            {"path": "docs/old.md", "line": 3, "side": "LEFT", "analysis": "The deleted claim was obsolete."}
        ],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "External links were not crawled.",
            "probes": [
                {
                    "path": "docs/old.md",
                    "line": 3,
                    "side": "LEFT",
                    "hypothesis": "The obsolete claim remains documented.",
                    "attack_or_counterexample": "Inspect the deletion-side hunk.",
                    "evidence": "The only changed line deletes the obsolete claim.",
                    "outcome": "falsified",
                }
            ],
        },
    }
    noema.validate_substantive_verdict(verdict, diff)
    verdict["reviewed_lines"][0]["line"] = 4
    with pytest.raises(RuntimeError, match="not an exact changed-side line"):
        noema.validate_substantive_verdict(verdict, diff)


def test_request_changes_requires_confirmed_probe_at_finding_location():
    diff = """diff --git a/config.yml b/config.yml
--- a/config.yml
+++ b/config.yml
@@ -1 +1 @@
-safe: true
+safe: false
"""
    verdict = {
        "decision": "request_changes",
        "summary": "The safety gate is disabled.",
        "findings": [{"severity": "high", "file": "config.yml", "line": 1, "side": "RIGHT", "message": "Keep the gate enabled."}],
        "reviewed_lines": [
            {"path": "config.yml", "line": 1, "side": "RIGHT", "analysis": "The new value disables the gate."}
        ],
        "adversarial_validation": {
            "status": "failed",
            "residual_risk": "No runtime override was inspected.",
            "probes": [
                {
                    "path": "config.yml",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The safety gate is disabled.",
                    "attack_or_counterexample": "Read the effective changed value.",
                    "evidence": "The RIGHT-side value is false.",
                    "outcome": "confirmed",
                },
                {
                    "path": "config.yml",
                    "line": 1,
                    "side": "RIGHT",
                    "hypothesis": "The key was renamed instead.",
                    "attack_or_counterexample": "Compare the key name on both sides.",
                    "evidence": "Both sides retain the key name safe.",
                    "outcome": "falsified",
                },
            ],
        },
    }
    noema.validate_substantive_verdict(verdict, diff)
    verdict["findings"][0]["side"] = "LEFT"
    with pytest.raises(RuntimeError, match="confirmed probe on a published finding"):
        noema.validate_substantive_verdict(verdict, diff)
    verdict["findings"][0]["side"] = "RIGHT"
    verdict["adversarial_validation"]["probes"][0]["outcome"] = "falsified"
    with pytest.raises(RuntimeError, match="confirmed probe on a published finding"):
        noema.validate_substantive_verdict(verdict, diff)
    verdict["adversarial_validation"]["probes"][0]["outcome"] = "confirmed"
    verdict["findings"][0]["line"] = 2
    with pytest.raises(RuntimeError, match="confirmed probe on a published finding"):
        noema.validate_substantive_verdict(verdict, diff)


def test_format_review_evidence_renders_only_structured_entries():
    lines = noema.format_review_evidence(
        {
            "reviewed_lines": [None, {"path": "a.py", "line": 2, "side": "RIGHT", "analysis": "checked"}],
            "adversarial_validation": {
                "residual_risk": "none observed",
                "probes": [None, {"path": "a.py", "line": 2, "side": "RIGHT", "outcome": "falsified", "hypothesis": "breaks", "evidence": "source trace passes"}],
            },
        }
    )
    assert any("a.py:2" in line and "checked" in line for line in lines)
    assert any("falsified" in line and "source trace passes" in line for line in lines)


def test_parse_args_and_main(monkeypatch):
    head = "a" * 40
    parsed = noema.parse_args(
        ["--repo", "owner/repo", "--pr-number", "9", "--expected-head-sha", head]
    )
    assert parsed.repo == "owner/repo"
    assert parsed.pr_number == 9
    assert parsed.expected_head_sha == head

    seen = []
    monkeypatch.setattr(
        noema,
        "inspect_and_review",
        lambda repo, number, expected: seen.append((repo, number, expected)) or 0,
    )
    assert noema.main(
        ["--repo", "owner/repo", "--pr-number", "9", "--expected-head-sha", head]
    ) == 0
    assert seen == [("owner/repo", 9, head)]

    with pytest.raises(SystemExit, match="--pr-number must be positive"):
        noema.main(
            ["--repo", "owner/repo", "--pr-number", "0", "--expected-head-sha", head]
        )
