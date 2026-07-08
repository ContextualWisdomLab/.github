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


from pydantic_ai.models.test import TestModel


def make_settings(**overrides):
    """Build a NoemaSettings with test-friendly defaults."""
    values = {
        "llm_api_url": "https://llm.example.test/v1/chat/completions",
        "llm_api_key": "secret",
        "llm_model": "review-model",
        "review_token_source": "oidc",
        "codegraph_index_path": "",
        "max_tool_file_chars": 50,
    }
    values.update(overrides)
    return noema.NoemaSettings(**values)


def raise_runtime(*_args, **_kwargs):
    """Raise a RuntimeError to simulate a failed gh/codegraph subprocess."""
    raise RuntimeError("boom bearer secrettoken")


def test_load_settings_sources_and_parsing(monkeypatch):
    for key in (
        "NOEMA_LLM_API_URL",
        "NOEMA_LLM_API_KEY",
        "NOEMA_LLM_MODEL",
        "NOEMA_REVIEW_TOKEN_SOURCE",
        "NOEMA_CODEGRAPH_INDEX_PATH",
        "NOEMA_TOOL_MAX_FILE_CHARS",
        "NOEMA_SETTINGS_JSON",
    ):
        monkeypatch.delenv(key, raising=False)

    defaults = noema.load_settings({})
    assert defaults.llm_model == "noema-default"
    assert defaults.review_token_source == "NOEMA_REVIEW_TOKEN"
    assert defaults.max_tool_file_chars == noema.DEFAULT_TOOL_FILE_CHARS

    explicit = noema.load_settings(
        {
            "NOEMA_LLM_API_URL": " https://llm.test/v1 ",
            "NOEMA_LLM_API_KEY": "k",
            "NOEMA_LLM_MODEL": "m",
            "NOEMA_REVIEW_TOKEN_SOURCE": "src",
            "NOEMA_CODEGRAPH_INDEX_PATH": "/idx",
            "NOEMA_TOOL_MAX_FILE_CHARS": "1234",
        }
    )
    assert explicit.llm_api_url == "https://llm.test/v1"
    assert (explicit.llm_model, explicit.review_token_source, explicit.codegraph_index_path) == ("m", "src", "/idx")
    assert explicit.max_tool_file_chars == 1234

    assert noema.load_settings({"NOEMA_TOOL_MAX_FILE_CHARS": "not-int"}).max_tool_file_chars == noema.DEFAULT_TOOL_FILE_CHARS

    monkeypatch.setenv("NOEMA_SETTINGS_JSON", json.dumps({"NOEMA_LLM_MODEL": "kv-model"}))
    assert noema.load_settings().llm_model == "kv-model"

    monkeypatch.delenv("NOEMA_SETTINGS_JSON", raising=False)
    monkeypatch.setenv("NOEMA_LLM_MODEL", "env-model")
    assert noema.load_settings().llm_model == "env-model"


def test_validate_llm_endpoint(monkeypatch):
    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.validate_llm_endpoint("file:///etc/passwd")
    with pytest.raises(ValueError, match="URL must have a valid hostname"):
        noema.validate_llm_endpoint("http:///chat")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.validate_llm_endpoint("http://localhost/chat")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.validate_llm_endpoint("http://api.localhost/chat")
    with pytest.raises(ValueError, match="internal IP"):
        noema.validate_llm_endpoint("http://169.254.169.254/chat")

    monkeypatch.setattr(noema.socket, "getaddrinfo", raise_runtime_gaierror)
    noema.validate_llm_endpoint("https://unresolved.example.test/chat")

    monkeypatch.setattr(
        noema.socket,
        "getaddrinfo",
        lambda *a, **k: [(noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))],
    )
    with pytest.raises(ValueError, match="internal IP"):
        noema.validate_llm_endpoint("https://resolves-local.example.test/chat")

    monkeypatch.setattr(
        noema.socket,
        "getaddrinfo",
        lambda *a, **k: [
            (noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("not_an_ip", 0)),
            (noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        ],
    )
    noema.validate_llm_endpoint("https://public.example.test/chat")


def raise_runtime_gaierror(*_args, **_kwargs):
    """Raise socket.gaierror to simulate an unresolvable hostname."""
    raise noema.socket.gaierror("Name or service not known")


def test_derive_openai_base_url():
    assert noema.derive_openai_base_url("https://x/v1/chat/completions") == "https://x/v1"
    assert noema.derive_openai_base_url("https://x/v1/") == "https://x/v1"
    assert noema.derive_openai_base_url("/chat/completions") == "/chat/completions"


def test_tool_fetch_changed_file(monkeypatch):
    deps = noema.ReviewDeps("owner/repo", 3, "abc", make_settings(max_tool_file_chars=10))
    assert noema.tool_fetch_changed_file(deps, "  ").startswith("error: refusing")
    assert noema.tool_fetch_changed_file(deps, "/etc/passwd").startswith("error: refusing")
    assert noema.tool_fetch_changed_file(deps, "a/../b").startswith("error: refusing")

    monkeypatch.setattr(noema, "run", raise_runtime)
    failed = noema.tool_fetch_changed_file(deps, "src/app.py")
    assert failed.startswith("error: unable to fetch src/app.py")
    assert "secrettoken" not in failed

    captured = {}

    def fake_run(args, **_kwargs):
        captured["args"] = args
        return "X" * 50

    monkeypatch.setattr(noema, "run", fake_run)
    truncated = noema.tool_fetch_changed_file(deps, "src/app.py")
    assert truncated.endswith("...[truncated]...")
    assert "-f" in captured["args"] and any("ref=abc" in part for part in captured["args"])

    deps_no_sha = noema.ReviewDeps("owner/repo", 3, "", make_settings(max_tool_file_chars=1000))
    monkeypatch.setattr(noema, "run", lambda args, **_kwargs: "short")
    assert noema.tool_fetch_changed_file(deps_no_sha, "src/app.py") == "short"


def test_tool_fetch_review_threads(monkeypatch):
    deps = noema.ReviewDeps("owner/repo", 3, "abc", make_settings())
    monkeypatch.setattr(noema, "run", raise_runtime)
    assert noema.tool_fetch_review_threads(deps).startswith("error: unable to fetch review threads")

    monkeypatch.setattr(noema, "run", lambda *a, **k: "not json")
    assert noema.tool_fetch_review_threads(deps) == "error: review thread response was not valid JSON"

    monkeypatch.setattr(noema, "run", lambda *a, **k: "")
    assert noema.tool_fetch_review_threads(deps) == "No prior inline review comments."

    payload = json.dumps(
        [
            {"user": {"login": "alice"}, "path": "a.py", "line": 5, "body": "hi\nthere"},
            {"user": {}, "path": "b.py", "original_line": 9, "body": "x"},
            {"path": "c.py", "body": "no line"},
            "skip",
        ]
    )
    monkeypatch.setattr(noema, "run", lambda *a, **k: payload)
    out = noema.tool_fetch_review_threads(deps)
    assert "- alice @ a.py:5: hi there" in out
    assert "- unknown @ b.py:9: x" in out
    assert "- unknown @ c.py: no line" in out


def test_tool_query_codegraph(monkeypatch):
    deps_off = noema.ReviewDeps("owner/repo", 3, "abc", make_settings(codegraph_index_path=""))
    assert "not configured" in noema.tool_query_codegraph(deps_off, "q")

    deps = noema.ReviewDeps("owner/repo", 3, "abc", make_settings(codegraph_index_path="/idx"))
    assert noema.tool_query_codegraph(deps, "   ") == "error: codegraph query was empty"

    monkeypatch.setattr(noema, "run", raise_runtime)
    assert noema.tool_query_codegraph(deps, "impact of foo").startswith("error: codegraph query failed")

    monkeypatch.setattr(noema, "run", lambda args, **k: "graph result")
    assert noema.tool_query_codegraph(deps, "impact of foo") == "graph result"


def test_build_review_model_offline():
    model = noema.build_review_model(make_settings())
    assert isinstance(model, noema.OpenAIChatModel)
    assert model.model_name == "review-model"


def test_build_review_agent_invokes_all_tools(monkeypatch):
    monkeypatch.setattr(noema, "run", lambda *a, **k: "[]")
    settings = make_settings(codegraph_index_path="/idx")
    agent = noema.build_review_agent(settings, model=TestModel())
    deps = noema.ReviewDeps("owner/repo", 3, "abc", settings)
    result = agent.run_sync("review", deps=deps)
    assert result.output.decision in {"approve", "request_changes", "comment"}


def test_call_llm_unconfigured_returns_none():
    assert noema.call_llm("o/r", 1, make_pr(), "diff", False, settings=make_settings(llm_api_url="")) is None
    assert noema.call_llm("o/r", 1, make_pr(), "diff", False, settings=make_settings(llm_api_key="")) is None


def test_call_llm_runs_injected_and_built_agent(monkeypatch):
    monkeypatch.setattr(noema, "run", lambda *a, **k: "[]")
    settings = make_settings()
    agent = noema.build_review_agent(
        settings,
        model=TestModel(
            custom_output_args={
                "decision": "request_changes",
                "summary": "cross-file break",
                "findings": [{"severity": "high", "file": "a.py", "line": 3, "message": "boom"}],
            }
        ),
    )
    verdict = noema.call_llm("o/r", 2, make_pr(headRefOid="abc"), "diff", True, settings=settings, agent=agent)
    assert verdict["decision"] == "request_changes"
    assert verdict["summary"] == "cross-file break"
    assert verdict["findings"][0]["file"] == "a.py"

    built = {}
    original_build = noema.build_review_agent

    def fake_build(resolved):
        built["called"] = True
        return original_build(resolved, model=TestModel())

    monkeypatch.setattr(noema, "build_review_agent", fake_build)
    verdict2 = noema.call_llm("o/r", 2, make_pr(), "diff", False, settings=settings)
    assert verdict2["decision"] in {"approve", "request_changes", "comment"}
    assert built["called"]


def test_call_llm_default_settings_apply_ssrf_guard(monkeypatch):
    monkeypatch.delenv("NOEMA_SETTINGS_JSON", raising=False)
    monkeypatch.setenv("NOEMA_LLM_API_URL", "file:///etc/passwd")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "secret")
    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.call_llm("o/r", 1, make_pr(), "diff", False)


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
