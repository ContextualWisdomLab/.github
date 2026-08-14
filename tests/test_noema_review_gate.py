import base64
import json
import sys

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


def test_review_state_helpers_cover_current_head_logic():
    marker_body = "OpenCode reviewed the current-head bounded evidence and found no blocking issues."
    current = review(body=marker_body)
    old = review(commit="old", body=marker_body)
    pr = make_pr(reviews={"nodes": [old, current]})

    assert noema.review_author(current) == "opencode-agent"
    assert noema.review_author({}) == ""
    assert noema.review_commit(current) == "head"
    assert noema.review_commit({}) == ""
    assert noema.current_primary_approval(pr) == current
    assert noema.current_primary_approval(make_pr(reviews={"nodes": [old]})) is None
    assert noema.current_primary_approval(make_pr(reviews={"nodes": [review("COMMENTED", body=marker_body)]})) is None
    assert noema.current_primary_approval(make_pr(reviews={"nodes": [review(login="human", body=marker_body)]})) is None
    assert noema.current_primary_approval(
        make_pr(
            reviews={
                "nodes": [review(login="github-actions[bot]", body=marker_body)]
            }
        )
    ) is None
    assert noema.has_current_changes_requested(make_pr(reviews={"nodes": [review("CHANGES_REQUESTED")]}))
    assert not noema.has_current_changes_requested(make_pr(reviews={"nodes": [review("CHANGES_REQUESTED", commit="old")]}))
    assert noema.has_unresolved_threads(make_pr(reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]}))
    assert not noema.has_unresolved_threads(make_pr(reviewThreads={"nodes": [{"isResolved": False, "isOutdated": True}]}))


def test_review_state_helpers_reject_explicit_previous_head_evidence():
    current_head = "a" * 40
    previous_head = "b" * 40
    approval_marker = "Result: APPROVE"
    stale_approval = review(
        commit=current_head,
        body=f"{approval_marker}\n\n- Head SHA: `{previous_head}`",
    )
    exact_approval = review(
        commit=current_head,
        body=f"{approval_marker}\n\n- Head SHA: `{current_head}`",
    )
    stale_change_request = review(
        "CHANGES_REQUESTED",
        commit=current_head,
        body=f"Result: REQUEST_CHANGES\n\n- Head SHA: `{previous_head}`",
    )

    assert noema.current_primary_approval(
        make_pr(headRefOid=current_head, reviews={"nodes": [stale_approval]})
    ) is None
    assert noema.current_primary_approval(
        make_pr(headRefOid=current_head, reviews={"nodes": [exact_approval]})
    ) == exact_approval
    assert not noema.has_current_changes_requested(
        make_pr(headRefOid=current_head, reviews={"nodes": [stale_change_request]})
    )


def test_check_helpers_and_existing_noema_review():
    status_context = {"__typename": "StatusContext", "context": "ci", "state": "FAILURE"}
    check_run = {
        "__typename": "CheckRun",
        "name": "build",
        "status": "COMPLETED",
        "conclusion": "SUCCESS",
        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
    }
    failed_run = {
        "__typename": "CheckRun",
        "name": "lint",
        "status": "COMPLETED",
        "conclusion": "FAILURE",
        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
    }
    running_run = {
        "__typename": "CheckRun",
        "name": "slow",
        "status": "IN_PROGRESS",
        "conclusion": None,
        "checkSuite": {"workflowRun": {"workflow": {"name": "CI"}}},
    }

    assert noema.check_label(status_context) == "ci"
    assert noema.check_label(check_run) == "CI / build"
    blockers = noema.blocking_checks(
        make_pr(
            statusCheckRollup={
                "contexts": {
                    "nodes": [
                        status_context,
                        check_run,
                        failed_run,
                        running_run,
                        {"__typename": "CheckRun", "name": "Required Noema Review", "status": "IN_PROGRESS"},
                    ]
                }
            }
        )
    )
    assert "ci: FAILURE" in blockers
    assert "CI / lint: FAILURE" in blockers
    assert "CI / slow: IN_PROGRESS" in blockers
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


def test_current_actor_fetch_diff_and_json_extraction(monkeypatch):
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "noema\n")
    assert noema.current_actor() == "noema"
    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("no gh")))
    assert noema.current_actor() == ""

    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "x" * (noema.MAX_DIFF_CHARS + 5))
    diff, truncated = noema.fetch_diff("owner/repo", 1)
    assert truncated
    assert len(diff) == noema.MAX_DIFF_CHARS

    assert noema.extract_json_object('{"decision":"approve"}') == {"decision": "approve"}
    assert noema.extract_json_object('prefix {"decision":"comment"} suffix') == {"decision": "comment"}
    with pytest.raises(RuntimeError, match="did not contain"):
        noema.extract_json_object("not-json")


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
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
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
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    monkeypatch.delenv("NOEMA_CODEGRAPH_CONTEXT_PATH", raising=False)
    assert noema.load_codegraph_context() == ""

    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(tmp_path / "missing.md"))
    assert "CodeGraph context unavailable" in noema.load_codegraph_context()

    paths = [f"src/file_{index}.py" for index in range(noema.MAX_CONTEXT_FILES + 1)]
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: paths)
    monkeypatch.setattr(noema, "fetch_head_file_content", lambda repo, path, head_sha: "x")

    context = noema.changed_file_context("owner/repo", 7, "head")

    assert "1 changed files omitted from context budget" in context


def test_load_codegraph_context_rejects_workspace_escape(monkeypatch, tmp_path):
    """Traversal, absolute, and symlink paths outside the workspace are rejected."""
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    outside = tmp_path.parent / "passwd-shape"
    outside.write_text("root:x:0:0:root:/root:/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(outside))
    assert noema.load_codegraph_context() == (
        "CodeGraph context unavailable: path escapes the workspace."
    )

    monkeypatch.setenv(
        "NOEMA_CODEGRAPH_CONTEXT_PATH",
        str(tmp_path / "nested" / ".." / ".." / outside.name),
    )
    assert "path escapes the workspace" in noema.load_codegraph_context()

    link = tmp_path / "escape.md"
    link.symlink_to(outside)
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(link))
    assert "path escapes the workspace" in noema.load_codegraph_context()


def test_codegraph_context_root_and_resolve_failure(monkeypatch, tmp_path):
    """Workspace root prefers GITHUB_WORKSPACE and resolve errors stay closed."""
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    assert noema.codegraph_context_root() == tmp_path.resolve()
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.chdir(tmp_path)
    assert noema.codegraph_context_root() == tmp_path.resolve()

    class FailingPath(type(tmp_path)):
        """Path stand-in whose resolve always fails."""

        def resolve(self, *args, **kwargs):
            """Raise OSError to cover the confinement resolve failure."""
            raise OSError("resolve failed")

    monkeypatch.setattr(noema, "Path", FailingPath)
    assert noema.confined_codegraph_context_path("graph.md", tmp_path.resolve()) is None


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
        return FakeResponse({"choices": [{"message": {"content": '{"decision":"approve","summary":"ok","findings":[]}'}}]})

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
            {"severity": "high", "file": "a.py", "line": 3, "message": "bad"},
            {"severity": "low", "file": "b.py", "line": 0, "message": "note"},
            "skip",
            {"message": ""},
        ]
    )
    assert findings == ["- [high] a.py:3: bad", "- [low] b.py: note"]

    calls = []
    monkeypatch.setenv("NOEMA_REVIEW_TOKEN_SOURCE", "oidc")
    monkeypatch.setattr(noema, "run", lambda args, stdin=None: calls.append((args, json.loads(stdin))) or "")
    noema.submit_review(
        "owner/repo",
        7,
        make_pr(),
        "noema",
        {"decision": "request_changes", "summary": "fix it", "findings": [{"file": "a.py", "line": 1, "message": "bad"}]},
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
    marker_body = "OpenCode reviewed the current-head bounded evidence and found no blocking issues."
    clean_pr = make_pr(reviews={"nodes": [review(body=marker_body)]})
    calls = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok", "findings": []})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert calls

    calls.clear()
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    assert noema.inspect_and_review("owner/repo", 7) == 1
    assert calls == []

    cases = [
        (make_pr(isDraft=True), "noema"),
        (make_pr(reviews={"nodes": [review("CHANGES_REQUESTED"), review(body=marker_body)]}), "noema"),
        (make_pr(reviews={"nodes": [review(body=marker_body)]}, reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]}), "noema"),
        (make_pr(reviews={"nodes": [review(body=marker_body)]}, statusCheckRollup={"contexts": {"nodes": [{"__typename": "StatusContext", "context": "ci", "state": "FAILURE"}]}}), "noema"),
        (clean_pr, "opencode-agent"),
    ]
    for pr, actor in cases:
        calls.clear()
        monkeypatch.setattr(noema, "fetch_pr", lambda repo, number, pr=pr: pr)
        monkeypatch.setattr(noema, "current_actor", lambda actor=actor: actor)
        assert noema.inspect_and_review("owner/repo", 7) == 0
        assert calls == []



def test_existing_noema_review_cannot_bypass_primary_approval(monkeypatch):
    """A Noema verdict is never sufficient without current-head OpenCode approval."""
    noema_review = review(
        login="noema",
        body="<!-- noema-review-gate head_sha=head -->",
    )
    pr = make_pr(reviews={"nodes": [noema_review]})
    submitted = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(
        noema,
        "submit_review",
        lambda *args, **kwargs: submitted.append(args),
    )

    assert noema.inspect_and_review("owner/repo", 7) == 1
    assert submitted == []

    primary_review = review(
        body=(
            "OpenCode reviewed the current-head bounded evidence and found "
            "no blocking issues."
        )
    )
    pr = make_pr(reviews={"nodes": [primary_review, noema_review]})
    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert submitted == []


def test_parse_args_and_main(monkeypatch):
    parsed = noema.parse_args(["--repo", "owner/repo", "--pr-number", "9"])
    assert parsed.repo == "owner/repo"
    assert parsed.pr_number == 9

    seen = []
    monkeypatch.setattr(noema, "inspect_and_review", lambda repo, number: seen.append((repo, number)) or 0)
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9"]) == 0
    assert seen == [("owner/repo", 9)]

    with pytest.raises(SystemExit, match="--pr-number must be positive"):
        noema.main(["--repo", "owner/repo", "--pr-number", "0"])
