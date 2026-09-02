"""Unit tests for Noema orchestrator-sidecar SSRF allowlist."""

from __future__ import annotations

import http.server
import json
import threading
import urllib.request

import pytest

from scripts.ci import noema_review_gate as noema


class FakeResponse:
    """Minimal urlopen response for call_llm unit tests."""

    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

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
    monkeypatch.setattr(noema, "validate_substantive_verdict", lambda *_args: None)

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
    verdict = noema.call_llm("owner/repo", 1, pr, "diff", False, "head")
    assert verdict["decision"] == "approve"
    assert seen["url"] == "http://127.0.0.1:18080/v1/chat/completions"
    assert seen["model"] == "orchestrator/free"

    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://127.0.0.1:9/evil")
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("NOEMA_LLM_VIA_ORCHESTRATOR", "1")
    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://[::1]:18080/v1/chat/completions")
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")

    monkeypatch.setenv("NOEMA_LLM_API_URL", "http://localhost:18080/v1/chat/completions")
    with pytest.raises(ValueError, match="URL cannot target localhost"):
        noema.call_llm("owner/repo", 1, pr, "diff", False, "head")


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

    def public(host, port):
        return [(0, 0, 0, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(noema.socket, "getaddrinfo", public)
    assert noema.reject_private_llm_url(
        "https://llm.example.test/v1/chat/completions"
    ) == ["8.8.8.8"]

    def boom(host, port):
        raise noema.socket.gaierror("nxdomain")

    monkeypatch.setattr(noema.socket, "getaddrinfo", boom)
    with pytest.raises(ValueError, match="could not be resolved"):
        noema.reject_private_llm_url("https://missing.example.test/v1/chat")

    def garbage(host, port):
        return [(0, 0, 0, "", ("not-an-ip", 0))]

    monkeypatch.setattr(noema.socket, "getaddrinfo", garbage)
    with pytest.raises(ValueError, match="did not resolve to any usable IP"):
        noema.reject_private_llm_url("https://odd.example.test/v1/chat")


def test_reject_private_llm_url_returns_every_pinned_ip_for_public_dns(monkeypatch):
    """A validated public hostname returns every resolved IP, deduplicated."""
    monkeypatch.delenv("NOEMA_LLM_VIA_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)

    def multi(host, port):
        return [
            (0, 0, 0, "", ("8.8.8.8", 0)),
            (0, 0, 0, "", ("8.8.4.4", 0)),
            (0, 0, 0, "", ("8.8.8.8", 0)),
        ]

    monkeypatch.setattr(noema.socket, "getaddrinfo", multi)
    assert noema.reject_private_llm_url("https://llm.example.test/v1/chat") == [
        "8.8.8.8",
        "8.8.4.4",
    ]

    monkeypatch.setenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", "http://127.0.0.1:18080")
    assert (
        noema.reject_private_llm_url("http://127.0.0.1:18080/v1/chat/completions")
        == []
    )


@pytest.mark.parametrize(
    "embedded_v4_ipv6",
    [
        "::127.0.0.1",
        "::10.0.0.5",
        "64:ff9b::7f00:1",
    ],
)
def test_reject_private_llm_url_rejects_reserved_embedded_ipv4(
    monkeypatch, embedded_v4_ipv6
):
    """Reserved IPv6 forms embedding a private/loopback IPv4 target stay closed.

    ``is_private``/``is_loopback``/etc. alone miss the deprecated IPv4-
    compatible format (``::127.0.0.1``) and the NAT64 well-known prefix
    (``64:ff9b::/96``, e.g. ``64:ff9b::7f00:1`` = 127.0.0.1) -- both read
    ``is_reserved=True`` with no false positives against real public
    addresses, so that is the check that catches them (found by peer
    review, `trusting-wilbur-195f90-93`).
    """
    monkeypatch.delenv("NOEMA_LLM_VIA_ORCHESTRATOR", raising=False)
    monkeypatch.delenv("CONTEXTUAL_ORCHESTRATOR_BASE_URL", raising=False)

    def resolves_to_embedded(host, port):
        return [(0, 0, 0, "", (embedded_v4_ipv6, 0))]

    monkeypatch.setattr(noema.socket, "getaddrinfo", resolves_to_embedded)
    with pytest.raises(ValueError, match="URL cannot target internal IP addresses"):
        noema.reject_private_llm_url("https://llm.example.test/v1/chat")


def test_pinned_connection_handlers_selects_by_scheme():
    """The handler list is empty with no pinned IPs, else scheme-selected."""
    assert noema._pinned_connection_handlers("https://x.test/", []) == []
    handlers = noema._pinned_connection_handlers("https://x.test/", ["203.0.113.9"])
    assert len(handlers) == 1
    assert isinstance(handlers[0], noema._PinnedHTTPSHandler)
    handlers = noema._pinned_connection_handlers("http://x.test/", ["203.0.113.9"])
    assert len(handlers) == 1
    assert isinstance(handlers[0], noema._PinnedHTTPHandler)


def test_pinned_connection_handlers_skips_pinning_when_proxy_configured(monkeypatch):
    """A configured proxy for this scheme disables pinning entirely.

    The pinned connection classes dial the gateway IP directly and do not
    implement CONNECT tunneling or proxy dialing, so silently pinning
    through a configured proxy would connect to the wrong endpoint and
    break HTTPS entirely (Devin Review) -- falling back to an ordinary,
    proxy-routed request is the deliberate, safe behavior here.
    """
    monkeypatch.setattr(
        noema.urllib.request, "getproxies", lambda: {"https": "http://proxy.test:3128"}
    )
    assert noema._pinned_connection_handlers("https://x.test/", ["203.0.113.9"]) == []
    handlers = noema._pinned_connection_handlers("http://x.test/", ["203.0.113.9"])
    assert len(handlers) == 1
    assert isinstance(handlers[0], noema._PinnedHTTPHandler)

    monkeypatch.setattr(
        noema.urllib.request,
        "getproxies",
        lambda: {"http": "http://proxy.test:3128", "https": "http://proxy.test:3128"},
    )
    assert noema._pinned_connection_handlers("http://x.test/", ["203.0.113.9"]) == []


class _EchoHandler(http.server.BaseHTTPRequestHandler):
    """A tiny local HTTP server that echoes the request Host header."""

    def do_POST(self) -> None:  # noqa: N802 - stdlib naming convention
        """Reply 200 with the received Host header as the body."""
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        body = self.headers.get("Host", "").encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        """Silence the default per-request stderr logging."""


def test_pinned_http_connection_connects_to_pinned_ip_not_hostname():
    """The request reaches a real server via the pinned IP, bypassing DNS.

    The request URL names a hostname that cannot resolve (``.invalid`` is
    reserved by RFC 2606 to never resolve); the request only succeeds
    because ``_PinnedHTTPHandler`` connects directly to the pinned loopback
    IP instead of asking the socket layer to resolve that hostname.
    """
    server = http.server.HTTPServer(("127.0.0.1", 0), _EchoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        opener = urllib.request.build_opener(
            noema._PinnedHTTPHandler(pinned_ips=["127.0.0.1"])
        )
        request = urllib.request.Request(
            f"http://noema-dns-pin-test.invalid:{port}/echo",
            data=b"{}",
            method="POST",
        )
        with opener.open(request) as response:  # nosec B310
            body = response.read().decode("utf-8")
        assert body == f"noema-dns-pin-test.invalid:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_pinned_https_handler_opens_through_a_pinned_https_connection(monkeypatch):
    """https_open() wires do_open() to a pinned-IP HTTPSConnection factory."""
    captured = {}

    def fake_do_open(self, http_class, req):
        captured["http_class"] = http_class
        captured["req"] = req
        return "opened"

    monkeypatch.setattr(
        urllib.request.AbstractHTTPHandler, "do_open", fake_do_open
    )
    handler = noema._PinnedHTTPSHandler(pinned_ips=["8.8.8.8"])
    fake_req = object()
    assert handler.https_open(fake_req) == "opened"
    assert captured["req"] is fake_req
    conn = captured["http_class"]("llm.example.test")
    assert isinstance(conn, noema._PinnedHTTPSConnection)
    assert conn._pinned_ips == ["8.8.8.8"]
    assert conn._context is handler._context


def test_pinned_https_connection_verifies_original_hostname_via_sni(monkeypatch):
    """The TLS handshake pins the IP but keeps SNI/cert checks on the hostname."""
    calls = {}

    class FakeSocket:
        pass

    class FakeContext:
        def wrap_socket(self, sock, server_hostname):
            calls["sock"] = sock
            calls["server_hostname"] = server_hostname
            return "wrapped"

    fake_sock = FakeSocket()
    monkeypatch.setattr(
        noema.socket, "create_connection", lambda *a, **k: fake_sock
    )
    conn = noema._PinnedHTTPSConnection(
        "llm.example.test", pinned_ips=["203.0.113.9"], context=FakeContext()
    )
    conn.port = 443
    conn.connect()
    assert calls["sock"] is fake_sock
    assert calls["server_hostname"] == "llm.example.test"
    assert conn.sock == "wrapped"


def test_connect_to_pinned_ips_falls_back_to_next_address_on_failure(monkeypatch):
    """An unreachable first address falls through to the next validated one.

    Mirrors ``socket.create_connection``'s own multi-address fallback for a
    hostname target, without re-resolving the hostname (Devin Review): a
    multi-address gateway previously lost failover entirely once only the
    first resolved address was pinned.
    """
    attempts = []

    def fake_create_connection(address, timeout, source_address):
        attempts.append(address[0])
        if address[0] == "203.0.113.1":
            raise OSError("connection refused")
        return f"socket-for-{address[0]}"

    monkeypatch.setattr(noema.socket, "create_connection", fake_create_connection)
    result = noema._connect_to_pinned_ips(
        ["203.0.113.1", "203.0.113.2"], 443, None, None
    )
    assert attempts == ["203.0.113.1", "203.0.113.2"]
    assert result == "socket-for-203.0.113.2"

    attempts.clear()
    with pytest.raises(OSError, match="connection refused"):
        noema._connect_to_pinned_ips(["203.0.113.1"], 443, None, None)
    assert attempts == ["203.0.113.1"]
