"""Contract tests for Noema's independent current-head review gate."""

import base64
import json
from types import SimpleNamespace

import pytest

from scripts.ci import noema_review_gate as noema


def fake_secret(*parts: str) -> str:
    """Join secret fragments so tests never spell a token as one literal."""
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
    """Validate subprocess safety, repository parsing, and basic API access."""
    calls = []

    def fake_run(argv, **kwargs):
        """Capture the safe subprocess invocation and return JSON text."""
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

    monkeypatch.setattr(noema.subprocess, "run", fake_run)
    assert noema.run(["gh", "api", "user"]).strip() == "ok"
    assert calls[0][0] == ["gh", "api", "user"]
    assert calls[0][1]["shell"] is False
    with pytest.raises(TypeError):
        noema.run("echo unsafe")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        noema.run(["python", "-c", "print('unsafe')"])
    with pytest.raises(TypeError):
        noema.run(["gh", 1])  # type: ignore[list-item]

    assert noema.split_repo("owner/repo") == ("owner", "repo")

def test_scrub_sensitive_data():
    """Redact common credentials while preserving harmless text."""
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
    """Redact bearer and basic authorization header values."""
    assert noema.scrub_sensitive_data("Authorization: Basic dXNlcjpwYXNz") == "Authorization: Basic ***"
    assert noema.scrub_sensitive_data("Proxy-Authorization: Basic dXNlcjpwYXNz") == "Proxy-Authorization: Basic ***"
    assert noema.scrub_sensitive_data("authorization: bearer xyz") == "authorization: bearer ***"


def test_split_repo_and_graphql(monkeypatch):
    """Reject malformed repository names and decode GraphQL responses."""
    with pytest.raises(ValueError):
        noema.split_repo("owner")
    with pytest.raises(ValueError):
        noema.split_repo("/repo")
    with pytest.raises(ValueError):
        noema.split_repo("owner/repo;id")

    calls = []

    def fake_run(args, stdin=None):
        """Return a deterministic pull-request GraphQL response."""
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
    """Accept only current-head primary approval and detect active blockers."""
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
    """Reject review bodies that explicitly cite a superseded head."""
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
    """Classify failed, running, and completed checks plus Noema markers."""
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
    """Cover actor fallback, bounded diffs, and JSON extraction errors."""
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
    """Build review context from changed files, threads, and CodeGraph evidence."""
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
        """Return deterministic command output for context assembly."""
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
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", "codegraph.md")
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
    """Explain omitted files and missing indexes instead of hiding evidence gaps."""
    monkeypatch.delenv("NOEMA_CODEGRAPH_CONTEXT_PATH", raising=False)
    assert noema.load_codegraph_context() == ""


def test_codegraph_context_rejects_paths_outside_workspace(monkeypatch, tmp_path):
    """Reject traversal, absolute, and symlink paths before reading context."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    monkeypatch.chdir(workspace)

    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", str(outside))
    assert "within the workspace" in noema.load_codegraph_context()

    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", "../outside.md")
    assert "within the workspace" in noema.load_codegraph_context()

    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", r"..\outside.md")
    assert "within the workspace" in noema.load_codegraph_context()

    link = workspace / "context.md"
    link.symlink_to(outside)
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", "context.md")
    assert "symlinked paths" in noema.load_codegraph_context()


def test_codegraph_context_reads_bounded_workspace_file(monkeypatch, tmp_path):
    """Read a regular workspace context file without unbounded allocation."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "context.md").write_text("trusted context", encoding="utf-8")
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("NOEMA_CODEGRAPH_CONTEXT_PATH", "context.md")
    assert noema.load_codegraph_context() == "trusted context"

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
    """Exercise valid, malformed, and unavailable LLM response paths."""
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
        """Record request data and return a deterministic approval response."""
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"choices": [{"message": {"content": '{"decision":"approve","summary":"ok","findings":[]}'}}]})

    # Since we replaced urlopen with build_opener, we mock build_opener
    class FakeOpener:
        """Provide a configurable opener for URL and redirect tests."""

        def __init__(self, call_func):
            """Store the callback used for the next request."""
            self.call_func = call_func
        def open(self, request, timeout=None):
            """Delegate the request to the configured fake callback."""
            return self.call_func(request, timeout)

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    verdict = noema.call_llm("owner/repo", 1, pr, "diff", True, "extra review context")
    assert verdict["decision"] == "approve"
    assert seen["url"] == "https://llm.example.test/chat"
    assert seen["body"]["model"] == "review-model"
    assert "extra review context" in seen["body"]["messages"][1]["content"]

    def fake_urlopen_defer(request, timeout=None):
        """Return a response with an unsupported decision."""
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

    # Loopback is allowed (same-job contextual-orchestrator sidecar): NOEMA_LLM_API_URL
    # is only ever set from a trusted repo/org Actions variable, never PR content.
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://localhost/chat")
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://127.0.0.1:8000/v1/chat/completions")
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

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

    # A hostname that resolves to loopback via DNS is allowed too, same as a
    # literal "localhost"/"127.0.0.1" -- the guard now permits any loopback
    # target, not just those two spellings.
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://resolved-to-local.example.com/chat")
    def fake_getaddrinfo(host, port, *args, **kwargs):
        """Resolve the test hostname to an allowed loopback address."""
        if host == "resolved-to-local.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    # Non-loopback internal ranges (private, link-local, multicast, unspecified)
    # stay blocked regardless of loopback now being permitted.
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://resolved-to-private.example.com/chat")
    def fake_getaddrinfo_private(host, port, *args, **kwargs):
        """Resolve the test hostname to a blocked private address."""
        if host == "resolved-to-private.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_private)
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Multiple addrinfo records (e.g. dual-stack A + AAAA), none of which raise:
    # the loop must continue past the first record to check the rest, not stop
    # after the first non-raising entry.
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://dual-stack.example.com/chat")
    def fake_getaddrinfo_dual_stack(host, port, *args, **kwargs):
        """Resolve to two public addresses for multi-record validation."""
        if host == "dual-stack.example.com":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("1.1.1.1", 0)),
            ]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_dual_stack)
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    # A loopback result must not short-circuit validation of later DNS results.
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://mixed-resolution.example.com/chat")

    def fake_getaddrinfo_mixed(host, port, *args, **kwargs):
        """Resolve to loopback and private addresses for fail-closed validation."""
        if host == "mixed-resolution.example.com":
            return [
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0)),
            ]
        return original_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_mixed)
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Test unresolved hostname does not break
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://unresolved.example.com/chat")
    def fake_getaddrinfo_error(host, port, *args, **kwargs):
        """Raise a resolver error to cover unresolved-host handling."""
        raise socket.gaierror("Name or service not known")
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_error)
    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    # Test invalid IP string from getaddrinfo (unlikely but theoretically possible)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://weird-dns.example.com/chat")
    def fake_getaddrinfo_invalid_ip(host, port, *args, **kwargs):
        """Return malformed address data to cover defensive parsing."""
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
        """Fail DNS resolution while testing URL scheme validation."""
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
    """Format bounded findings and submit the exact current-head review."""
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
    """Skip draft, stale, blocked, and already-reviewed pull requests."""
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

    cases = [
        (make_pr(), "noema"),
        (make_pr(isDraft=True), "noema"),
        (make_pr(reviews={"nodes": [review(login="noema", body="<!-- noema-review-gate head_sha=head -->")]}), "noema"),
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


def test_parse_args_and_main(monkeypatch):
    """Parse CLI arguments and reject non-positive pull-request numbers."""
    parsed = noema.parse_args(["--repo", "owner/repo", "--pr-number", "9"])
    assert parsed.repo == "owner/repo"
    assert parsed.pr_number == 9

    seen = []
    monkeypatch.setattr(noema, "inspect_and_review", lambda repo, number: seen.append((repo, number)) or 0)
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9"]) == 0
    assert seen == [("owner/repo", 9)]

    with pytest.raises(SystemExit, match="--pr-number must be positive"):
        noema.main(["--repo", "owner/repo", "--pr-number", "0"])
