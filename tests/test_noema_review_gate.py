import io
import json
import os
import sys
import urllib.error

import pytest

from scripts.ci import noema_review_gate as noema


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
    assert noema.scrub_sensitive_data("github_pat_123456789") == "***"
    assert noema.scrub_sensitive_data("ghp_12345") == "***"
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
    assert noema.has_current_changes_requested(make_pr(reviews={"nodes": [review("CHANGES_REQUESTED")]}))
    assert not noema.has_current_changes_requested(make_pr(reviews={"nodes": [review("CHANGES_REQUESTED", commit="old")]}))
    assert noema.has_unresolved_threads(make_pr(reviewThreads={"nodes": [{"isResolved": False, "isOutdated": False}]}))
    assert not noema.has_unresolved_threads(make_pr(reviewThreads={"nodes": [{"isResolved": False, "isOutdated": True}]}))


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
    assert noema.existing_noema_review(
        make_pr(reviews={"nodes": [review(login="noema", body="<!-- noema-review-gate head_sha=head -->")]}),
        "noema",
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
    assert noema.call_llm("owner/repo", 1, pr, "diff", False) is None

    monkeypatch.setenv("NOEMA_LLM_API_URL", "file:///etc/passwd")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    with pytest.raises(ValueError, match="must start with http:// or https://"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example.test/chat")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "review-model")
    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"choices": [{"message": {"content": '{"decision":"approve","summary":"ok","findings":[]}'}}]})

    monkeypatch.setattr(noema.urllib.request, "urlopen", fake_urlopen)
    verdict = noema.call_llm("owner/repo", 1, pr, "diff", True)
    assert verdict["decision"] == "approve"
    assert seen["url"] == "https://llm.example.test/chat"
    assert seen["body"]["model"] == "review-model"

    monkeypatch.setattr(
        noema.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse({"choices": [{"message": {"content": '{"decision":"defer"}'}}]}),
    )
    with pytest.raises(RuntimeError, match="unsupported decision"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # Test case-insensitive valid URL
    monkeypatch.setenv("NOEMA_LLM_API_URL", "HTTPS://llm.example.test/chat")
    monkeypatch.setattr(noema.urllib.request, "urlopen", fake_urlopen)
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
    monkeypatch.setattr(noema.urllib.request, "urlopen", fake_urlopen)
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"

    # Test invalid IP string from getaddrinfo (unlikely but theoretically possible)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://weird-dns.example.com/chat")
    def fake_getaddrinfo_invalid_ip(host, port, *args, **kwargs):
        if host == "weird-dns.example.com":
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("not_an_ip", 0))]
        return original_getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo_invalid_ip)
    assert noema.call_llm("owner/repo", 1, pr, "diff", True)["decision"] == "approve"


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

    calls.clear()
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: None)
    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert calls == []


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
