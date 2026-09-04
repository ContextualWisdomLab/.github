"""Exact contracts for Noema's single gateway request and passive telemetry."""

import json

import pytest

from scripts.ci import noema_review_gate as gate


@pytest.fixture(autouse=True)
def _default_gateway_dns_resolves_public(monkeypatch):
    """Resolve any unmocked gateway hostname to a fixed public IP.

    This module's tests use a non-resolving example hostname for
    ``NOEMA_LLM_API_URL`` and mock the HTTP response layer directly, with
    no interest in DNS behavior itself. ``reject_private_llm_url`` now
    fails closed on a resolution failure (Devin Review) rather than
    silently allowing the URL through unpinned, so these tests need a
    resolvable hostname to reach the transport behavior they actually
    test.
    """
    monkeypatch.setattr(
        gate.socket,
        "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )


DIFF = """diff --git a/README.md b/README.md
index 1111111..2222222 100644
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


def _verdict() -> dict:
    return {
        "decision": "approve",
        "summary": "Reviewed the exact changed line.",
        "reviewed_lines": [{"path": "README.md", "line": 1, "side": "RIGHT", "analysis": "Bounded replacement."}],
        "adversarial_validation": {
            "status": "passed",
            "residual_risk": "No additional risk identified.",
            "probes": [{
                "path": "README.md", "line": 1, "side": "RIGHT",
                "hypothesis": "The replacement could be wrong.",
                "attack_or_counterexample": "Inspect the exact changed line.",
                "evidence": "The new value is present at the cited line.",
                "outcome": "falsified",
            }],
        },
        "findings": [],
    }


def _configure(monkeypatch, raw: bytes):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    requests = []

    class Response:
        def __enter__(self): return self
        def __exit__(self, *_args): return None
        def read(self): return raw

    def open_response(_opener, request, **kwargs):
        requests.append(request)
        assert kwargs == {}
        return Response()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    return requests


def test_success_uses_one_request_and_one_phase_annotation(monkeypatch, capsys) -> None:
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": json.dumps(_verdict())}}]}).encode()
    requests = _configure(monkeypatch, raw)
    verdict = gate.call_llm("owner/repo", 7, {"title": "t", "headRefOid": "a" * 40}, DIFF, False, "a" * 40, changed_paths=("README.md",))
    assert verdict["decision"] == "approve"
    assert len(requests) == 1
    output = capsys.readouterr().out
    assert output.count("::notice::Noema gateway attempt") == 1
    assert "phase=validating" in output
    assert "caller attempts=1" in output
    # The requested gateway alias (orchestrator/free by default) is always
    # known upfront and reported alongside served_model, even on success.
    assert "requested_model=orchestrator/free" in output
    assert "served_model=provider/model" in output


def test_transport_failure_reports_requested_model_and_not_literal_connecting(
    monkeypatch, capsys
) -> None:
    """An HTTPError (a real status line came back) must not blame "connecting".

    ``opener.open()`` is one blocking call spanning DNS/TCP/TLS setup, the
    request, AND the wait for the upstream response -- for a loopback
    gateway sidecar that connects near-instantly, an HTTPError here means
    the connection, handshake, and request send all succeeded and a real
    (if unwelcome) status code came back, so the delay was almost always
    the upstream provider being slow to respond, not a network
    connectivity problem. See the sibling
    ``test_definitively_pre_send_failures_report_connecting`` and
    ``test_ambiguous_transport_failures_default_to_awaiting_response`` for
    the two Devin Review follow-ups this went through: only a conclusively
    pre-send exception may report "connecting"; anything ambiguous (a
    timeout that could belong to either phase) safely defaults to
    "awaiting_response". An HTTPError is not ambiguous -- it proves a real
    response arrived -- so it gets its own, more specific "response_error"
    phase instead of the ambiguous-case default.
    """
    calls, kwargs = _invoke_once(
        monkeypatch,
        open_error=lambda request: gate.urllib.error.HTTPError(
            request.full_url, 500, "Internal Server Error", {}, None
        ),
    )
    with pytest.raises(gate.NoemaTransportError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "phase=response_error" in output
    assert "phase=connecting" not in output
    assert "phase=awaiting_response" not in output
    assert "requested_model=orchestrator/free" in output
    assert "served_model=unknown" in output


def test_malformed_output_fails_closed_without_caller_retry(monkeypatch, capsys) -> None:
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": "not-json"}}]}).encode()
    requests = _configure(monkeypatch, raw)
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm("owner/repo", 7, {"title": "t", "headRefOid": "b" * 40}, DIFF, False, "b" * 40, changed_paths=("README.md",))
    assert len(requests) == 1
    output = capsys.readouterr().out
    assert output.count("::warning::Noema gateway attempt") == 1


def test_served_model_is_annotation_safe() -> None:
    """A model id carrying CRLF/GHA-annotation/control characters is rejected
    outright, not sanitized and kept -- it prints as ``served_model=unknown``
    in the ``::warning::``/``::notice::`` lines, so nothing it contains can
    ever reach GitHub Actions' workflow-command parser."""
    raw = json.dumps({"model": "bad\r\n::error::boom\u0000\ud800"})
    assert gate._extract_served_model(raw) is None


def test_served_model_accepts_a_real_provider_id() -> None:
    raw = json.dumps({"model": "deepseek-ai/deepseek-v4-pro-0813"})
    assert gate._extract_served_model(raw) == "deepseek-ai/deepseek-v4-pro-0813"


@pytest.mark.parametrize("text", ["[,]", "{,}", "[1,,]", '{"a":,}'])
def test_local_json_repair_never_fabricates_missing_values(text: str) -> None:
    assert gate._strip_trailing_commas_outside_strings(text) == text


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a":"x",}', '{"a":"x"}'),
        ('{"a":1,}', '{"a":1}'),
        ('{"a":true,}', '{"a":true}'),
        ('{"a":null,}', '{"a":null}'),
        ('{"a":{},}', '{"a":{}}'),
        ('{"a":[],}', '{"a":[]}'),
        ('["x",]', '["x"]'),
        ('[1,]', '[1]'),
    ],
)
def test_local_json_repair_accepts_only_complete_value_trailing_commas(text: str, expected: str) -> None:
    assert gate._strip_trailing_commas_outside_strings(text) == expected


def _single_request_transport(monkeypatch, *, raw=None, open_error=None, read_error=None):
    monkeypatch.setenv("NOEMA_LLM_API_URL", "https://llm.example/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "test-key")
    calls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            if read_error is not None:
                raise read_error
            assert raw is not None
            return raw

    def open_response(_opener, request, **kwargs):
        calls.append(request)
        assert kwargs == {}
        if open_error is not None:
            raise open_error(request) if callable(open_error) else open_error
        return Response()

    monkeypatch.setattr(gate.urllib.request.OpenerDirector, "open", open_response)
    return calls


def _invoke_once(monkeypatch, **transport):
    calls = _single_request_transport(monkeypatch, **transport)
    kwargs = dict(
        repo="owner/repo",
        number=7,
        pr={"title": "t", "headRefOid": "c" * 40},
        diff=DIFF,
        truncated=False,
        expected_head="c" * 40,
        changed_paths=("README.md",),
    )
    return calls, kwargs


def test_malformed_gateway_envelope_is_one_request_fail_closed(monkeypatch) -> None:
    calls, kwargs = _invoke_once(monkeypatch, raw=b"[]")
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


def test_invalid_utf8_is_one_request_fail_closed(monkeypatch) -> None:
    calls, kwargs = _invoke_once(monkeypatch, raw=b"invalid: \x80\x81\xfe")
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        lambda request: gate.urllib.error.HTTPError(request.full_url, 502, "Bad Gateway", {}, None),
        OSError("socket timeout"),
    ],
)
def test_connect_failures_are_one_request_and_typed(monkeypatch, failure) -> None:
    calls, kwargs = _invoke_once(monkeypatch, open_error=failure)
    with pytest.raises(gate.NoemaTransportError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


@pytest.mark.parametrize(
    "failure",
    [
        gate.urllib.error.URLError(ConnectionRefusedError("refused")),
        gate.urllib.error.URLError(gate.socket.gaierror("name resolution failed")),
        gate.urllib.error.URLError(gate.ssl.SSLError("handshake failed")),
        ConnectionRefusedError("refused"),
    ],
)
def test_definitively_pre_send_failures_report_connecting(monkeypatch, capsys, failure) -> None:
    """Only an exception that PROVES no request was ever sent -- a refused
    connection, a DNS lookup failure, or a failed TLS handshake -- may
    report "connecting". Devin Review's original follow-up on the
    awaiting_response rename: don't let a genuine connection failure get
    mislabeled as provider latency either.
    """
    calls, kwargs = _invoke_once(monkeypatch, open_error=failure)
    with pytest.raises(gate.NoemaTransportError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "phase=connecting" in output
    assert "phase=awaiting_response" not in output


@pytest.mark.parametrize(
    "failure",
    [
        OSError("socket timeout"),
        TimeoutError("timed out"),
        gate.urllib.error.URLError("Connection refused"),
        gate.urllib.error.URLError(TimeoutError("timed out")),
    ],
)
def test_ambiguous_transport_failures_default_to_awaiting_response(
    monkeypatch, capsys, failure
) -> None:
    """A generic/timeout-shaped transport error does NOT prove which side
    of the request stalled -- urlopen's single blocking call has no hook to
    tell a connect-phase timeout from a response-phase one apart. Devin
    Review's second follow-up: don't claim the false precision of
    "connecting" for these; "awaiting_response" is the honest, safe
    default (and matches the common case for this loopback sidecar, where
    a genuine connect failure is rare).
    """
    calls, kwargs = _invoke_once(monkeypatch, open_error=failure)
    with pytest.raises(gate.NoemaTransportError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "phase=awaiting_response" in output
    assert "phase=connecting" not in output


def test_truncated_read_is_one_request_and_typed(monkeypatch) -> None:
    calls, kwargs = _invoke_once(
        monkeypatch, read_error=gate.http.client.IncompleteRead(b"partial", 10)
    )
    with pytest.raises(gate.NoemaTransportError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


def test_malformed_verdict_json_is_not_retried(monkeypatch) -> None:
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": "{bad"}}]}).encode()
    calls, kwargs = _invoke_once(monkeypatch, raw=raw)
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1


def test_rejected_changed_line_verdict_is_not_retried(monkeypatch) -> None:
    verdict = _verdict()
    verdict["decision"] = "request_changes"
    verdict["findings"] = [{
        "severity": "high",
        "file": "README.md",
        "line": 99,
        "side": "RIGHT",
        "message": "Outside the changed hunk.",
    }]
    raw = json.dumps({"model": "provider/model", "choices": [{"message": {"content": json.dumps(verdict)}}]}).encode()
    calls, kwargs = _invoke_once(monkeypatch, raw=raw)
    with pytest.raises(gate.NoemaModelOutputError, match="caller attempts=1"):
        gate.call_llm(**kwargs)
    assert len(calls) == 1
