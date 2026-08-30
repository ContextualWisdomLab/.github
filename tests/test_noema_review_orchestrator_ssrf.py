"""Unit tests for Noema orchestrator-sidecar SSRF allowlist."""

from __future__ import annotations

import json

import pytest

from scripts.ci import noema_review_gate as noema


class FakeResponse:
    """Minimal urlopen response for call_llm unit tests."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self, size=-1):
        """Return at most the requested number of encoded JSON bytes."""
        return self._payload if size < 0 else self._payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def make_pr(**overrides):
    """Return a minimal PR payload for call_llm."""
    pr = {"title": "t", "headRefOid": "head"}
    pr.update(overrides)
    return pr


def test_truthy_env_and_loopback_literal_helpers(monkeypatch):
    """Cover explicit flag parsing and the sidecar loopback-host allowlist."""
    monkeypatch.delenv("NOEMA_LLM_VIA_ORCHESTRATOR", raising=False)
    assert noema._truthy_env("NOEMA_LLM_VIA_ORCHESTRATOR") is False
    for value in ("0", "false", "no", "off", ""):
        monkeypatch.setenv("NOEMA_LLM_VIA_ORCHESTRATOR", value)
        assert noema._truthy_env("NOEMA_LLM_VIA_ORCHESTRATOR") is False
    for value in ("1", "TRUE", "Yes", "on"):
        monkeypatch.setenv("NOEMA_LLM_VIA_ORCHESTRATOR", value)
        assert noema._truthy_env("NOEMA_LLM_VIA_ORCHESTRATOR") is True
    assert noema._is_loopback_literal_host("127.0.0.1")
    assert noema._is_loopback_literal_host("::1")
    assert not noema._is_loopback_literal_host("localhost")
    assert not noema._is_loopback_literal_host("10.0.0.1")


def test_http_origin_rejects_non_http_userinfo_and_maps_default_ports():
    """Cover every _http_origin branch used by the sidecar allowlist."""
    parse = noema.urllib.parse.urlparse
    assert noema._http_origin(parse("ftp://127.0.0.1/chat")) is None
    assert noema._http_origin(parse("http:///chat")) is None
    assert noema._http_origin(parse("http://user:pass@127.0.0.1:18080/chat")) is None
    assert noema._http_origin(parse("http://:secret@127.0.0.1:18080/chat")) is None
    assert noema._http_origin(parse("http://127.0.0.1:999999/chat")) is None
    assert noema._http_origin(parse("http://127.0.0.1/v1/chat")) == ("http", "127.0.0.1", 80)
    assert noema._http_origin(parse("https://127.0.0.1/v1/chat")) == ("https", "127.0.0.1", 443)
    assert noema._http_origin(parse("http://[::1]:18080/v1/chat")) == ("http", "::1", 18080)


def test_allowed_orchestrator_sidecar_url_requires_exact_configured_origin(monkeypatch):
    """The marker flag must not widen the exact sidecar-origin allowlist."""
    monkeypatch.delenv("NOEMA_LLM_VIA_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)
    sidecar = "http://127.0.0.1:18080/v1/chat/completions"
    assert noema.is_allowed_orchestrator_sidecar_url("https://llm.example.test/chat") is False
    assert noema.is_allowed_orchestrator_sidecar_url("file:///etc/passwd") is False
    assert noema.is_allowed_orchestrator_sidecar_url(sidecar) is False

    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://127.0.0.1:18080")
    assert noema.is_allowed_orchestrator_sidecar_url(sidecar) is True
    assert noema.is_allowed_orchestrator_sidecar_url("http://[::1]:18080/v1/chat/completions") is False
    assert noema.is_allowed_orchestrator_sidecar_url("http://127.0.0.1:9999/v1/chat/completions") is False
    assert noema.is_allowed_orchestrator_sidecar_url("https://127.0.0.1:18080/v1/chat/completions") is False

    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://example.test:18080")
    assert noema.is_allowed_orchestrator_sidecar_url(sidecar) is False

    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://user:pass@127.0.0.1:18080")
    assert noema.is_allowed_orchestrator_sidecar_url(sidecar) is False

    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("NOEMA_LLM_VIA_ORCHESTRATOR", "1")
    assert noema.is_allowed_orchestrator_sidecar_url(sidecar) is False
    assert noema.is_allowed_orchestrator_sidecar_url("http://[::1]:18080/v1/chat/completions") is False
    assert noema.is_allowed_orchestrator_sidecar_url("http://localhost:18080/v1/chat/completions") is False

    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://127.0.0.1:18080")
    assert noema.is_allowed_orchestrator_sidecar_url(sidecar) is True
    assert noema.is_allowed_orchestrator_sidecar_url("http://127.0.0.1:18081/v1/chat/completions") is False


def test_reject_private_llm_url_allows_sidecar_and_keeps_ssrf_closed(monkeypatch):
    """Sidecar loopback is the only private target; localhost and other RFC1918 stay closed."""
    monkeypatch.delenv("NOEMA_LLM_VIA_ORCHESTRATOR", raising=False)
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://127.0.0.1:18080")
    noema.reject_private_llm_url("http://127.0.0.1:18080/v1/chat/completions")

    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.reject_private_llm_url("http://127.0.0.1:18080/v1/chat/completions")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.reject_private_llm_url("http://localhost:18080/v1/chat/completions")
    monkeypatch.setenv("NOEMA_LLM_VIA_ORCHESTRATOR", "true")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.reject_private_llm_url("http://localhost:18080/v1/chat/completions")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.reject_private_llm_url("http://agent.localhost/v1/chat")
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.reject_private_llm_url("http://[::1]:18080/v1/chat/completions")


def test_call_llm_allows_matching_orchestrator_sidecar_loopback(monkeypatch):
    """A sidecar-origin loopback URL reaches the LLM client; other loopbacks do not."""
    pr = make_pr()
    monkeypatch.setenv("NOEMA_LLM_API_KEY", "sidecar-bearer")
    monkeypatch.setenv("NOEMA_LLM_MODEL", "orchestrator/free")
    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://127.0.0.1:18080")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://127.0.0.1:18080/v1/chat/completions")

    seen = {}

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["model"] = json.loads(request.data.decode("utf-8"))["model"]
        return FakeResponse({"choices": [{"message": {"content": '{\"decision\":\"approve\",\"summary\":\"ok\",\"findings\":[]}'}}]})

    class FakeOpener:
        def __init__(self, call_func):
            self.call_func = call_func

        def open(self, request, timeout=None):
            return self.call_func(request, timeout)

    monkeypatch.setattr(noema.urllib.request, "build_opener", lambda *args: FakeOpener(fake_urlopen))
    verdict = noema.call_llm("owner/repo", 1, pr, "diff", False)
    assert verdict["decision"] == "approve"
    assert seen["url"] == "http://127.0.0.1:18080/v1/chat/completions"
    assert seen["model"] == "orchestrator/free"

    # A loopback literal on a port that does not match the configured sidecar
    # origin is not the trusted sidecar, so it falls through to the ordinary
    # non-loopback path and is rejected for using plaintext HTTP.
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://127.0.0.1:9/evil")
    with pytest.raises(ValueError, match="non-loopback endpoints must use HTTPS"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    # The via-orchestrator marker never widens the allowlist on its own; with
    # no CONTEXTUAL_ORCHESTRATOR_BASE_URL configured this is not the sidecar
    # either, so it is rejected the same way.
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("NOEMA_LLM_VIA_ORCHESTRATOR", "1")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://[::1]:18080/v1/chat/completions")
    with pytest.raises(ValueError, match="non-loopback endpoints must use HTTPS"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)

    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://localhost:18080/v1/chat/completions")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.call_llm("owner/repo", 1, pr, "diff", False)


def test_reject_private_llm_url_scheme_hostname_and_public_dns(monkeypatch):
    """Keep non-http, empty-host, and DNS-to-private closed; allow public HTTPS."""
    with pytest.raises(ValueError, match="must start"):
        noema.reject_private_llm_url("ftp://example.test/chat")
    with pytest.raises(ValueError, match="must start"):
        noema.reject_private_llm_url("/relative")
    with pytest.raises(ValueError, match="URL must have a valid hostname"):
        noema.reject_private_llm_url("http:///v1/chat")
    monkeypatch.delenv("NOEMA_LLM_VIA_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)
    noema.reject_private_llm_url("https://llm.example.test/v1/chat/completions")

    def boom(host, port):
        raise noema.socket.gaierror("nxdomain")

    monkeypatch.setattr(noema.socket, "getaddrinfo", boom)
    noema.reject_private_llm_url("https://missing.example.test/v1/chat")

    def garbage(host, port):
        return [(0, 0, 0, "", ("not-an-ip", 0))]

    monkeypatch.setattr(noema.socket, "getaddrinfo", garbage)
    noema.reject_private_llm_url("https://odd.example.test/v1/chat")

    def public(host, port):
        return [(noema.socket.AF_INET, noema.socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(noema.socket, "getaddrinfo", public)
    noema.reject_private_llm_url("https://public.example.test/v1/chat")


def test_reject_private_llm_url_keeps_parsed_scheme_guard_as_defense_in_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A string that starts with https:// but reparses to a non-http(s) scheme
    still fails closed; this is not reachable through ordinary input and is
    exercised directly since `call_llm` no longer routes through this
    function for its own (validate_endpoint-based) request path."""
    parsed = noema.urllib.parse.ParseResult("file", "llm.example.test", "/chat", "", "", "")
    monkeypatch.setattr(noema.urllib.parse, "urlparse", lambda _: parsed)

    with pytest.raises(ValueError, match="URL scheme must be http or https"):
        noema.reject_private_llm_url("https://llm.example.test/chat")
