import base64
import http.server
import json
import sys
import threading
import time

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

    monkeypatch.setattr(noema, "run", lambda *args, **kwargs: "x" * (noema.MAX_DIFF_CHARS + 5))
    diff, truncated = noema.fetch_diff("owner/repo", 1)
    assert truncated
    assert len(diff) == noema.MAX_DIFF_CHARS

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

    def read(self, amt=None):
        """Return the payload as encoded JSON bytes, then an empty chunk."""
        if getattr(self, "_read_done", False):
            return b""
        self._read_done = True
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


def test_llm_request_timeout_matches_org_two_hour_per_model_policy():
    """call_llm's per-attempt HTTP timeout must itself be the full per-model policy bound.

    Regression guard, round two, for the recurring `TimeoutError` at this exact
    call site (ContextualWisdomLab/contextual-orchestrator#965, #958, #960).
    Round one (ContextualWisdomLab/.github#1509) set the per-attempt timeout to
    3600s (half the two-hour policy), reasoning that call_llm's at-most-one
    repair-retry recursion made "two 1-hour attempts" equal the org's stated
    two-hour-per-model-call policy (docs/product-goal-directive.md). That
    reasoning was itself a bug, caught by Devin Review on the same PR: the
    repair retry only fires when the model's response FAILS
    validate_substantive_verdict, never because the HTTP call itself ran long,
    so a single genuinely-slow-but-healthy call needing e.g. 90 minutes would
    hit a 3600s timeout and fail despite never needing a retry and staying
    within the org's per-model allowance. Each attempt is an independent model
    call under the org's policy and must therefore individually get the full
    two-hour bound. Per-attempt and overall-budget assertions are pinned
    separately here (rather than only their product) per Devin Review's
    explicit ask, so a future edit cannot silently shrink either one back
    toward either bug already fixed.
    """
    assert noema.LLM_REQUEST_TIMEOUT_SECONDS == 7200
    max_call_llm_attempts_per_review = 2  # original call + at most one repair retry
    assert noema.LLM_REQUEST_TOTAL_BUDGET_SECONDS == 14400
    assert (
        noema.LLM_REQUEST_TIMEOUT_SECONDS * max_call_llm_attempts_per_review
        == noema.LLM_REQUEST_TOTAL_BUDGET_SECONDS
    )


def test_call_llm_enforces_monotonic_deadline_on_a_slow_trickling_response(monkeypatch):
    """call_llm must not let a trickling response outlive the total budget.

    Regression coverage for CodeRabbit's finding on ContextualWisdomLab/.github#1509:
    ``opener.open(..., timeout=LLM_REQUEST_TIMEOUT_SECONDS)`` only bounds the
    connection phase and each individual socket read (confirmed CPython
    ``urllib.request``/``socket`` timeout semantics), not the cumulative time
    spent in ``response.read()``. A server that keeps trickling small amounts
    of data at intervals shorter than that per-read timeout could otherwise
    keep a still-alive connection open past ``LLM_REQUEST_TOTAL_BUDGET_SECONDS``.

    This spins up a real local HTTP server (through the loopback sidecar
    allowlist, not a mock) that sends its body in small delayed chunks whose
    total duration comfortably exceeds a monkeypatched, deliberately tiny
    ``LLM_REQUEST_TOTAL_BUDGET_SECONDS``, and asserts call_llm fails closed
    with a clear error well before the full trickle would have completed --
    proving the deadline is enforced mid-read, not just once per attempt.
    """
    chunk_delay_seconds = 0.3
    chunk_count = 12  # 3.6s of total trickle time, well over the budget below

    class SlowTrickleHandler(http.server.BaseHTTPRequestHandler):
        """A local HTTP handler that dribbles its body out in small pieces."""

        def do_POST(self):
            """Consume the request body, then trickle a slow, chunked reply."""
            content_length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(content_length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for _ in range(chunk_count):
                    self.wfile.write(b" ")
                    self.wfile.flush()
                    time.sleep(chunk_delay_seconds)
            except OSError:
                pass  # The client is expected to disconnect once its deadline fires.

        def log_message(self, *_args):
            """Silence the default per-request stderr logging."""

    server = http.server.HTTPServer(("127.0.0.1", 0), SlowTrickleHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        origin = f"http://127.0.0.1:{server.server_address[1]}"
        monkeypatch.setenv("NOEMA_LLM_API_URL", f"{origin}/v1/chat/completions")
        monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
        # Route through the loopback sidecar allowlist (is_allowed_orchestrator_sidecar_url)
        # so reject_private_llm_url permits this 127.0.0.1 target.
        monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", origin)
        monkeypatch.setattr(noema, "LLM_REQUEST_TOTAL_BUDGET_SECONDS", 1.0)
        monkeypatch.setattr(noema, "LLM_REQUEST_TIMEOUT_SECONDS", 10)

        start = time.monotonic()
        with pytest.raises(RuntimeError, match="LLM_REQUEST_TOTAL_BUDGET_SECONDS"):
            noema.call_llm("owner/repo", 7, make_pr(), "diff", False)
        elapsed = time.monotonic() - start
    finally:
        server.shutdown()
        server_thread.join(timeout=5)

    # Must abort close to the 1.0s budget, not after the full ~3.6s trickle
    # and not after the (monkeypatched to 10s) per-attempt LLM_REQUEST_TIMEOUT_SECONDS.
    assert elapsed < chunk_count * chunk_delay_seconds


def test_read_response_body_within_deadline_rejects_already_expired_deadline():
    """An already-passed deadline must fail before any read is attempted."""

    class _UnreadableResponse:
        def read(self):
            raise AssertionError("must not be called once the deadline has passed")

    with pytest.raises(RuntimeError, match="before the response body could be read"):
        noema._read_response_body_within_deadline(_UnreadableResponse(), time.monotonic() - 1)


def test_read_response_body_within_deadline_tolerates_a_failing_shutdown():
    """A watchdog whose shutdown() itself fails must still fail closed on timeout."""

    class _FailingRawSocket:
        def shutdown(self, how):
            raise OSError("shutdown not supported by this fake socket")

    class _Raw:
        def __init__(self, sock):
            self._sock = sock

    class _SlowResponse:
        def __init__(self):
            self.fp = type("Fp", (), {"raw": _Raw(_FailingRawSocket())})()

        def read(self):
            time.sleep(0.2)  # long enough for the watchdog to have already fired
            return b"partial body despite the failed shutdown"

    with pytest.raises(RuntimeError, match="while reading the response body"):
        noema._read_response_body_within_deadline(_SlowResponse(), time.monotonic() + 0.05)


def test_read_response_body_within_deadline_converts_reset_after_watchdog_fires():
    """A read() that raises OSError once the watchdog has fired must fail closed."""

    class _RawSocket:
        def __init__(self):
            self.shutdown_called = threading.Event()

        def shutdown(self, how):
            self.shutdown_called.set()

    class _Raw:
        def __init__(self, sock):
            self._sock = sock

    class _ResetOnShutdownResponse:
        def __init__(self):
            self._sock = _RawSocket()
            self.fp = type("Fp", (), {"raw": _Raw(self._sock)})()

        def read(self):
            self._sock.shutdown_called.wait(timeout=5)
            raise OSError("connection reset by the watchdog's shutdown()")

    with pytest.raises(RuntimeError, match="while reading the response body"):
        noema._read_response_body_within_deadline(_ResetOnShutdownResponse(), time.monotonic() + 0.05)


def test_read_response_body_within_deadline_reraises_unrelated_os_error():
    """An OSError raised before the watchdog ever fires must propagate unchanged."""

    class _RawSocket:
        def shutdown(self, how):
            raise AssertionError("must not be called; the read fails before any timeout")

    class _Raw:
        def __init__(self, sock):
            self._sock = sock

    class _ImmediatelyBrokenResponse:
        def __init__(self):
            self.fp = type("Fp", (), {"raw": _Raw(_RawSocket())})()

        def read(self):
            raise OSError("connection reset by peer, unrelated to the deadline")

    with pytest.raises(OSError, match="unrelated to the deadline"):
        noema._read_response_body_within_deadline(_ImmediatelyBrokenResponse(), time.monotonic() + 5)


def test_call_llm_rejects_an_already_expired_deadline_before_any_request(monkeypatch):
    """call_llm's own top-of-function budget check must fail closed pre-request.

    This also guards the repair-retry recursion: if the original attempt
    consumed the entire LLM_REQUEST_TOTAL_BUDGET_SECONDS, the recursive
    repair call (which threads the same shared deadline through) must not
    silently get a fresh timeout budget instead of failing closed.
    """
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("must not attempt a network call past the deadline")

    monkeypatch.setattr(noema.urllib.request, "build_opener", fail_if_called)
    with pytest.raises(RuntimeError, match="before this attempt could start"):
        noema.call_llm(
            "owner/repo", 7, make_pr(), "diff", False, deadline=time.monotonic() - 1
        )


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
    clean_pr = make_pr()
    calls = []
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok", "findings": []})
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))

    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert calls

    cases = [
        (make_pr(isDraft=True), "noema"),
        (make_pr(reviews={"nodes": [review(login="noema", body="<!-- noema-review-gate head_sha=head -->")]}), "noema"),
    ]
    for pr, actor in cases:
        calls.clear()
        monkeypatch.setattr(noema, "fetch_pr", lambda repo, number, pr=pr: pr)
        monkeypatch.setattr(noema, "current_actor", lambda actor=actor: actor)
        assert noema.inspect_and_review("owner/repo", 7) == 0
        assert calls == []

    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "")
    with pytest.raises(RuntimeError, match="identity could not be verified"):
        noema.inspect_and_review("owner/repo", 7)

    monkeypatch.setattr(noema, "current_actor", lambda: "opencode-agent")
    with pytest.raises(RuntimeError, match="independent reviewer credential"):
        noema.inspect_and_review("owner/repo", 7)


def test_inspect_and_review_does_not_wait_for_other_reviews_or_checks(monkeypatch):
    pr = make_pr(
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

    assert noema.inspect_and_review("owner/repo", 7) == 0
    assert calls


def test_run_review_phase_returns_state_or_none(monkeypatch):
    """run_review_phase must hand back JSON-serializable state, or None to skip.

    Regression coverage for ContextualWisdomLab/.github#1509's second Devin
    Review finding: the workflow now mints a fresh submission credential
    between computing a verdict and submitting it, which required splitting
    inspect_and_review's single pass into a review phase (this function) and a
    submit phase (submit_pending_verdict). run_review_phase must never call
    submit_review itself.
    """
    clean_pr = make_pr()
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: clean_pr)
    monkeypatch.setattr(noema, "current_actor", lambda: "noema")
    monkeypatch.setattr(noema, "fetch_diff", lambda repo, number: ("diff", False))
    monkeypatch.setattr(noema, "fetch_changed_file_paths", lambda repo, number: ["tool.py"])
    monkeypatch.setattr(noema, "build_review_context", lambda repo, number, pr: "context")
    monkeypatch.setattr(
        noema, "call_llm", lambda *args, **kwargs: {"decision": "approve", "summary": "ok", "findings": []}
    )
    monkeypatch.setattr(
        noema, "submit_review", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not submit"))
    )

    state = noema.run_review_phase("owner/repo", 7)
    assert state == {
        "pr": clean_pr,
        "actor": "noema",
        "verdict": {"decision": "approve", "summary": "ok", "findings": []},
    }

    draft_pr = make_pr(isDraft=True)
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: draft_pr)
    assert noema.run_review_phase("owner/repo", 7) is None


def test_write_and_load_review_state_round_trip(tmp_path):
    """Review-phase state must round-trip through JSON for the submit phase."""
    state_path = str(tmp_path / "noema-review-state.json")
    assert noema.load_review_state(state_path) is None

    state = {"pr": make_pr(), "actor": "cwl-noema-review[bot]", "verdict": {"decision": "comment"}}
    noema.write_review_state(state_path, state)
    assert noema.load_review_state(state_path) == state


def test_submit_pending_verdict_matches_and_rejects_identity_drift(monkeypatch):
    """submit_pending_verdict must re-verify identity against the fresh credential.

    Regression coverage for ContextualWisdomLab/.github#1509's second Devin
    Review finding: a long call_llm can outlive the credential minted before
    it, so the workflow mints a fresh one before submitting. This must not
    silently trust the identity recorded when the verdict was computed --
    a mismatch (e.g. a misconfigured refresh binding a different identity)
    must fail closed rather than post under an unverified identity.
    """
    calls = []
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(noema, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr())
    state = {
        "pr": make_pr(),
        "actor": "cwl-noema-review[bot]",
        "verdict": {"decision": "approve", "summary": "ok", "findings": []},
    }
    noema.submit_pending_verdict("owner/repo", 7, state)
    assert calls == [("owner/repo", 7, state["pr"], "cwl-noema-review[bot]", state["verdict"])]

    calls.clear()
    monkeypatch.setattr(noema, "current_actor", lambda: "a-different-identity[bot]")
    with pytest.raises(RuntimeError, match="does not match the identity"):
        noema.submit_pending_verdict("owner/repo", 7, state)
    assert calls == []

    monkeypatch.setattr(noema, "current_actor", lambda: "")
    with pytest.raises(RuntimeError, match="identity could not be verified"):
        noema.submit_pending_verdict("owner/repo", 7, state)


def test_submit_pending_verdict_rejects_stale_head_between_phases(monkeypatch):
    """submit_pending_verdict must refuse to submit against a moved PR head.

    Regression coverage for CodeRabbit's finding on ContextualWisdomLab/.github#1509:
    submit_pending_verdict did not re-call fetch_pr before submit_review, so a new
    commit landing during the (now up to ~4-hour) window between run_review_phase
    persisting state and this phase running would silently submit a verdict
    attached to a stale commit_id -- directly undermining this org's exact-head
    evidence model (PR_GOVERNANCE_AUDIT.md: "Old approvals and old checks are not
    merge evidence after the head SHA changes"). fetch_pr must now be re-called
    here, and a headRefOid mismatch must abort before submit_review is ever
    called.
    """
    calls = []
    monkeypatch.setattr(noema, "submit_review", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(noema, "current_actor", lambda: "cwl-noema-review[bot]")
    monkeypatch.setattr(noema, "fetch_pr", lambda repo, number: make_pr(headRefOid="new-commit-landed"))
    state = {
        "pr": make_pr(headRefOid="stale-head"),
        "actor": "cwl-noema-review[bot]",
        "verdict": {"decision": "approve", "summary": "ok", "findings": []},
    }
    with pytest.raises(RuntimeError, match="PR head changed"):
        noema.submit_pending_verdict("owner/repo", 7, state)
    assert calls == []


def test_call_llm_rejects_empty_review_content(monkeypatch):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, amt=None):
            if getattr(self, "_read_done", False):
                return b""
            self._read_done = True
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

        def read(self, amt=None):
            if getattr(self, "_read_done", False):
                return b""
            self._read_done = True
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

        def read(self, amt=None):
            if getattr(self, "_read_done", False):
                return b""
            self._read_done = True
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

        def read(self, amt=None):
            if getattr(self, "_read_done", False):
                return b""
            self._read_done = True
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
            self._read_done = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, amt=None):
            if self._read_done:
                return b""
            self._read_done = True
            return json.dumps(
                {"choices": [{"message": {"content": json.dumps(self.verdict)}}]}
            ).encode()

    class Opener:
        def open(self, request, timeout):
            assert timeout == noema.LLM_REQUEST_TIMEOUT_SECONDS
            payloads.append(json.loads(request.data))
            return Response(invalid if len(payloads) == 1 else valid)

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *_args: Opener())

    assert noema.call_llm("owner/repo", 7, make_pr(), diff, False)["decision"] == "approve"
    assert len(payloads) == 2
    assert "trusted validator" in payloads[1]["messages"][1]["content"]
    # Evidence for LLM_REQUEST_TIMEOUT_SECONDS applying unchanged to a repair
    # retry (ContextualWisdomLab/.github#1509, Devin Review): the repair
    # attempt resends the SAME full diff as the original attempt, not a
    # smaller patch, so it is not typically a cheaper/faster call and gets no
    # smaller a timeout budget than the original.
    original_content = payloads[0]["messages"][1]["content"]
    repair_content = payloads[1]["messages"][1]["content"]
    assert original_content.count(diff) == 1
    assert repair_content.count(diff) == 1
    assert len(repair_content) >= len(original_content)


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
    parsed = noema.parse_args(["--repo", "owner/repo", "--pr-number", "9"])
    assert parsed.repo == "owner/repo"
    assert parsed.pr_number == 9
    assert parsed.phase is None
    assert parsed.state_file is None

    seen = []
    monkeypatch.setattr(noema, "inspect_and_review", lambda repo, number: seen.append((repo, number)) or 0)
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9"]) == 0
    assert seen == [("owner/repo", 9)]

    with pytest.raises(SystemExit, match="--pr-number must be positive"):
        noema.main(["--repo", "owner/repo", "--pr-number", "0"])


def test_main_phase_requires_state_file(monkeypatch):
    """--phase without --state-file must fail closed, for either phase value."""
    for phase in ("review", "submit"):
        with pytest.raises(SystemExit, match="--state-file is required with --phase"):
            noema.main(["--repo", "owner/repo", "--pr-number", "9", "--phase", phase])


def test_main_review_phase_writes_state_only_when_computed(monkeypatch, tmp_path):
    """--phase review must persist state on success and write nothing to skip."""
    state_path = str(tmp_path / "state.json")
    monkeypatch.setattr(noema, "run_review_phase", lambda repo, number: {"pr": {}, "actor": "noema", "verdict": {}})
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9", "--phase", "review", "--state-file", state_path]) == 0
    assert noema.load_review_state(state_path) == {"pr": {}, "actor": "noema", "verdict": {}}

    skip_path = str(tmp_path / "skip.json")
    monkeypatch.setattr(noema, "run_review_phase", lambda repo, number: None)
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9", "--phase", "review", "--state-file", skip_path]) == 0
    assert noema.load_review_state(skip_path) is None


def test_main_submit_phase_submits_or_skips(monkeypatch, tmp_path):
    """--phase submit must submit persisted state, or skip cleanly when absent."""
    missing_path = str(tmp_path / "missing.json")
    monkeypatch.setattr(
        noema, "submit_pending_verdict", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not submit"))
    )
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9", "--phase", "submit", "--state-file", missing_path]) == 0

    state_path = str(tmp_path / "state.json")
    state = {"pr": {}, "actor": "noema", "verdict": {}}
    noema.write_review_state(state_path, state)
    seen = []
    monkeypatch.setattr(noema, "submit_pending_verdict", lambda repo, number, s: seen.append((repo, number, s)))
    assert noema.main(["--repo", "owner/repo", "--pr-number", "9", "--phase", "submit", "--state-file", state_path]) == 0
    assert seen == [("owner/repo", 9, state)]
