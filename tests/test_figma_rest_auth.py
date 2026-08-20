"""Contracts for Cloud Agent Figma REST authentication."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import figma_rest_auth as auth

ROOT = Path(__file__).resolve().parents[1]
DOCTORING = ROOT / "docs" / "doctoring" / "figma-cloud-agent-mcp-auth.md"
AGENTS = ROOT / "AGENTS.md"
MASTER = ROOT / "docs" / "CWL-MASTER-CONTEXT.md"
TOKEN = "figd_test_token_must_never_appear"


def _whoami_body(**fields: str) -> bytes:
    """Return a Figma ``/v1/me`` JSON body."""
    return json.dumps(fields).encode("utf-8")


def test_read_access_token_requires_nonempty_secret() -> None:
    """Missing or blank tokens fail closed without treating MCP as available."""
    with pytest.raises(auth.FigmaAuthError) as missing:
        auth.read_access_token({})
    assert missing.value.exit_code == auth.EXIT_MISSING_TOKEN
    assert auth.TOKEN_ENV_NAME in str(missing.value)

    with pytest.raises(auth.FigmaAuthError) as blank:
        auth.read_access_token({auth.TOKEN_ENV_NAME: "  \n"})
    assert blank.value.exit_code == auth.EXIT_MISSING_TOKEN
    assert "empty" in str(blank.value)


def test_read_access_token_strips_whitespace() -> None:
    """Surrounding whitespace is not part of the stored secret."""
    assert auth.read_access_token({auth.TOKEN_ENV_NAME: f"  {TOKEN}\n"}) == TOKEN


def test_read_access_token_rejects_embedded_control_characters() -> None:
    """A multiline secret cannot reach ``X-Figma-Token`` (CWE-113)."""
    with pytest.raises(auth.FigmaAuthError) as control:
        auth.read_access_token({auth.TOKEN_ENV_NAME: f"{TOKEN}\r\ninjected"})
    assert control.value.exit_code == auth.EXIT_MISSING_TOKEN
    assert "control" in str(control.value)
    assert TOKEN not in str(control.value)


def test_identity_field_normalizes_scalar_values() -> None:
    """Booleans and non-text values never become identity tokens."""
    assert auth.identity_field(True) is None
    assert auth.identity_field(3.14) is None
    assert auth.identity_field(["x"]) is None
    assert auth.identity_field("  ") is None
    assert auth.identity_field(0) == "0"


def test_identity_summary_omits_unknown_fields() -> None:
    """Identity lines stay token-free and tolerate a sparse payload."""
    assert auth.identity_summary({}) == "Figma REST authentication succeeded."
    assert (
        auth.identity_summary(
            {"handle": "seonghobae", "id": "123", "email": "user@example.com"}
        )
        == "Figma REST authentication succeeded "
        "(handle=seonghobae, id=123, email=user@example.com)."
    )
    assert auth.identity_summary({"handle": "  ", "id": 17}) == (
        "Figma REST authentication succeeded (id=17)."
    )
    assert auth.identity_summary({"handle": "a\nb", "id": True}) == (
        "Figma REST authentication succeeded (handle=a b)."
    )


def test_parse_whoami_payload_rejects_non_objects() -> None:
    """Non-JSON and non-object bodies are transport failures, not auth success."""
    with pytest.raises(auth.FigmaAuthError) as invalid_json:
        auth.parse_whoami_payload(b"not-json")
    assert invalid_json.value.exit_code == auth.EXIT_TRANSPORT

    with pytest.raises(auth.FigmaAuthError) as not_object:
        auth.parse_whoami_payload(b'["me"]')
    assert not_object.value.exit_code == auth.EXIT_TRANSPORT

    with pytest.raises(auth.FigmaAuthError):
        auth.parse_whoami_payload(b"\xff")


def test_verify_rest_auth_accepts_valid_token() -> None:
    """A 200 ``/v1/me`` response is the Cloud Agent auth success signal."""
    seen: dict[str, Any] = {}

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Capture the fixed endpoint and return a valid identity payload."""
        seen["url"] = url
        seen["headers"] = dict(headers)
        return 200, _whoami_body(handle="seonghobae", id="abc")

    summary = auth.verify_rest_auth({auth.TOKEN_ENV_NAME: TOKEN}, opener)

    assert seen["url"] == auth.WHOAMI_URL
    assert seen["headers"] == {auth.TOKEN_HEADER: TOKEN}
    assert "handle=seonghobae" in summary
    assert TOKEN not in summary


@pytest.mark.parametrize("status", [401, 403])
def test_verify_rest_auth_rejects_unauthorized_token(status: int) -> None:
    """Figma 401/403 mean the secret must be rotated, not that MCP is up."""

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return the parametrized authentication rejection response."""
        del url, headers
        return status, b'{"status":403,"err":"Invalid token"}'

    with pytest.raises(auth.FigmaAuthError) as rejected:
        auth.verify_rest_auth({auth.TOKEN_ENV_NAME: TOKEN}, opener)
    assert rejected.value.exit_code == auth.EXIT_REJECTED
    assert str(status) in str(rejected.value)
    assert TOKEN not in str(rejected.value)


def test_verify_rest_auth_treats_unexpected_status_as_transport() -> None:
    """Non-auth HTTP failures stay distinct from a missing or rejected token."""

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return a non-authentication transport failure."""
        del url, headers
        return 503, b"unavailable"

    with pytest.raises(auth.FigmaAuthError) as transport:
        auth.verify_rest_auth({auth.TOKEN_ENV_NAME: TOKEN}, opener)
    assert transport.value.exit_code == auth.EXIT_TRANSPORT
    assert "503" in str(transport.value)


class _FakeWhoamiResponse:
    """Minimal ``HTTPResponse`` stand-in for ``HTTPSConnection.getresponse``."""

    def __init__(self, status: int, body: bytes) -> None:
        """Record the canned status and body."""
        self.status = status
        self._body = body

    def read(self, amt: int | None = None) -> bytes:
        """Return the canned body, honoring an optional byte limit."""
        if amt is None:
            return self._body
        return self._body[:amt]


class _FakeWhoamiConnection:
    """Record the pinned Figma origin used by ``default_opener``."""

    last: _FakeWhoamiConnection | None = None

    def __init__(self, host: str, timeout: int = 0) -> None:
        """Capture the TLS host and timeout."""
        self.host = host
        self.timeout = timeout
        self.method = ""
        self.path = ""
        self.headers: dict[str, str] = {}
        self.closed = False
        self._status = 200
        self._body = b'{"handle":"ok"}'
        type(self).last = self

    def request(self, method: str, path: str, headers: dict[str, str] | None = None) -> None:
        """Record the fixed GET /v1/me call."""
        self.method = method
        self.path = path
        self.headers = dict(headers or {})

    def getresponse(self) -> _FakeWhoamiResponse:
        """Return the canned whoami response."""
        return _FakeWhoamiResponse(self._status, self._body)

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


def test_default_opener_rejects_non_whoami_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    """``file://`` and other caller URLs never reach the TLS sink."""
    constructed: list[object] = []

    def forbidden_connection(*args: object, **kwargs: object) -> object:
        """Fail if URL validation reaches the network constructor."""
        constructed.append((args, kwargs))
        raise AssertionError("whoami opener must not connect for a refused URL")

    monkeypatch.setattr(auth.http.client, "HTTPSConnection", forbidden_connection)
    with pytest.raises(auth.FigmaAuthError) as refused:
        auth.default_opener("file:///etc/passwd", {auth.TOKEN_HEADER: TOKEN})
    assert refused.value.exit_code == auth.EXIT_TRANSPORT
    assert "refuses" in str(refused.value)
    assert TOKEN not in str(refused.value)
    assert constructed == []
    with pytest.raises(auth.FigmaAuthError):
        auth.default_opener("https://api.figma.com/v1/files/TestFileKey0123456789", {})
    assert constructed == []


def test_default_opener_returns_http_error_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-200 Figma statuses stay as ``(status, body)`` for auth classification."""

    class ForbiddenConnection(_FakeWhoamiConnection):
        """Return HTTP 403 from the pinned origin."""

        def __init__(self, host: str, timeout: int = 0) -> None:
            """Initialize a 403 canned response."""
            super().__init__(host, timeout)
            self._status = 403
            self._body = b"nope"

    monkeypatch.setattr(auth.http.client, "HTTPSConnection", ForbiddenConnection)
    status, body = auth.default_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert status == 403
    assert body == b"nope"
    assert ForbiddenConnection.last is not None
    assert ForbiddenConnection.last.closed is True


def test_default_opener_reads_success_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful HTTPS response yields its status and body bytes."""
    monkeypatch.setattr(auth.http.client, "HTTPSConnection", _FakeWhoamiConnection)
    status, body = auth.default_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert status == 200
    assert body == b'{"handle":"ok"}'
    connection = _FakeWhoamiConnection.last
    assert connection is not None
    assert connection.host == "api.figma.com"
    assert connection.timeout == auth.REQUEST_TIMEOUT_SECONDS
    assert connection.method == "GET"
    assert connection.path == "/v1/me"
    assert connection.headers == {auth.TOKEN_HEADER: TOKEN}
    assert connection.closed is True


def test_default_opener_wraps_os_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network failures become ``EXIT_TRANSPORT`` without leaking the token."""

    class FailingConnection(_FakeWhoamiConnection):
        """Raise a transport error after the host is already pinned."""

        def request(self, method: str, path: str, headers: dict[str, str] | None = None) -> None:
            """Fail after recording the request."""
            super().request(method, path, headers)
            raise TimeoutError("timed out")

    monkeypatch.setattr(auth.http.client, "HTTPSConnection", FailingConnection)
    with pytest.raises(auth.FigmaAuthError) as transport:
        auth.default_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert transport.value.exit_code == auth.EXIT_TRANSPORT
    assert "timed out" in str(transport.value)
    assert TOKEN not in str(transport.value)
    assert FailingConnection.last is not None
    assert FailingConnection.last.closed is True


def test_sanitize_request_headers_allows_only_figma_token() -> None:
    """A Host or empty token header never reaches ``HTTPSConnection.request``."""
    assert auth.sanitize_request_headers({}) == {}
    assert auth.sanitize_request_headers({auth.TOKEN_HEADER: TOKEN}) == {
        auth.TOKEN_HEADER: TOKEN
    }
    with pytest.raises(auth.FigmaAuthError) as host:
        auth.sanitize_request_headers({auth.TOKEN_HEADER: TOKEN, "Host": "evil.example"})
    assert host.value.exit_code == auth.EXIT_TRANSPORT
    assert "Host" in str(host.value)
    assert TOKEN not in str(host.value)
    with pytest.raises(auth.FigmaAuthError) as blank:
        auth.sanitize_request_headers({auth.TOKEN_HEADER: "  "})
    assert blank.value.exit_code == auth.EXIT_TRANSPORT
    with pytest.raises(auth.FigmaAuthError) as control:
        auth.sanitize_request_headers({auth.TOKEN_HEADER: f"{TOKEN}\r\nHost: evil"})
    assert control.value.exit_code == auth.EXIT_TRANSPORT
    assert "control" in str(control.value)
    assert TOKEN not in str(control.value)


def test_read_bounded_body_rejects_oversize_and_nonpositive_limits() -> None:
    """Response bodies cannot grow past the configured byte cap."""
    assert auth.read_bounded_body(lambda amt: b"ok"[:amt], 8) == b"ok"
    with pytest.raises(auth.FigmaAuthError) as oversize:
        auth.read_bounded_body(lambda amt: b"x" * amt, 4)
    assert oversize.value.exit_code == auth.EXIT_TRANSPORT
    assert "4" in str(oversize.value)
    with pytest.raises(auth.FigmaAuthError) as invalid:
        auth.read_bounded_body(lambda amt: b"", 0)
    assert invalid.value.exit_code == auth.EXIT_TRANSPORT


def test_default_opener_rejects_oversize_whoami_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A whoami body larger than 64 KiB is a transport failure."""

    class HugeConnection(_FakeWhoamiConnection):
        """Return more bytes than the whoami cap."""

        def __init__(self, host: str, timeout: int = 0) -> None:
            """Initialize an oversized body."""
            super().__init__(host, timeout)
            self._body = b"x" * (auth.MAX_WHOAMI_BODY_BYTES + 1)

    monkeypatch.setattr(auth.http.client, "HTTPSConnection", HugeConnection)
    with pytest.raises(auth.FigmaAuthError) as oversize:
        auth.default_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert oversize.value.exit_code == auth.EXIT_TRANSPORT
    assert str(auth.MAX_WHOAMI_BODY_BYTES) in str(oversize.value)


def test_live_unauthenticated_whoami_is_rejected_by_figma() -> None:
    """The real ``/v1/me`` endpoint rejects a missing token with HTTP 401/403."""
    status, body = auth.default_opener(auth.WHOAMI_URL, {})
    assert status in {401, 403}
    assert TOKEN not in body.decode("utf-8", errors="replace")
    lowered = body.lower()
    assert b"token" in lowered or b"unauthorized" in lowered or b"invalid" in lowered


def test_helper_pins_https_origin_instead_of_dynamic_urllib() -> None:
    """Semgrep ``dynamic-urllib-use-detected`` must not apply to this helper."""
    source = Path(auth.__file__).read_text(encoding="utf-8")
    assert "urlopen(" not in source
    assert "http.client.HTTPSConnection" in source
    assert '"api.figma.com"' in source
    assert '"/v1/me"' in source


def test_main_writes_identity_and_error_channels() -> None:
    """CLI success and failure stay on stdout/stderr and never echo the token."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return a valid identity response for the CLI success path."""
        del url, headers
        return 200, _whoami_body(handle="seonghobae")

    ok = auth.main(
        argv=["figma_rest_auth.py"],
        environ={auth.TOKEN_ENV_NAME: TOKEN},
        opener=opener,
        stdout=stdout,
        stderr=stderr,
    )
    assert ok == auth.EXIT_OK
    assert "handle=seonghobae" in stdout.getvalue()
    assert stderr.getvalue() == ""
    assert TOKEN not in stdout.getvalue()

    missing_out = io.StringIO()
    missing_err = io.StringIO()
    missing = auth.main(
        argv=[],
        environ={},
        opener=opener,
        stdout=missing_out,
        stderr=missing_err,
    )
    assert missing == auth.EXIT_MISSING_TOKEN
    assert missing_out.getvalue() == ""
    assert auth.TOKEN_ENV_NAME in missing_err.getvalue()
    assert TOKEN not in missing_err.getvalue()

    rejected_out = io.StringIO()
    rejected_err = io.StringIO()

    def reject(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return an unauthorized response for the CLI error path."""
        del url, headers
        return 401, b'{"err":"Invalid token"}'

    rejected = auth.main(
        argv=[],
        environ={auth.TOKEN_ENV_NAME: TOKEN},
        opener=reject,
        stdout=rejected_out,
        stderr=rejected_err,
    )
    assert rejected == auth.EXIT_REJECTED
    assert rejected_out.getvalue() == ""
    assert "401" in rejected_err.getvalue()
    assert TOKEN not in rejected_err.getvalue()


def test_main_uses_process_streams_when_unspecified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default CLI path reads ``os.environ`` and writes process streams."""
    monkeypatch.setenv(auth.TOKEN_ENV_NAME, TOKEN)

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        """Return a valid identity response through process streams."""
        del url
        assert headers[auth.TOKEN_HEADER] == TOKEN
        return 200, _whoami_body(id="xyz")

    assert auth.main(opener=opener) == auth.EXIT_OK
    captured = capsys.readouterr()
    assert "id=xyz" in captured.out
    assert TOKEN not in captured.out


def test_doctoring_and_entry_docs_pin_cloud_agent_fallback() -> None:
    """Agents must not treat Figma MCP OAuth as available in Cloud Agents."""
    doctoring = DOCTORING.read_text(encoding="utf-8")
    agents = AGENTS.read_text(encoding="utf-8")
    master = MASTER.read_text(encoding="utf-8")
    for text in (doctoring, agents, master):
        assert "FIGMA_ACCESS_TOKEN" in text
        assert "mcp.figma.com" in text
    assert "X-Figma-Token" in doctoring
    assert "not supported in Cloud agents" in doctoring
    assert "https://api.figma.com/v1/me" in doctoring
    assert "scripts/ci/figma_rest_auth.py" in doctoring
    assert "docs/doctoring/figma-cloud-agent-mcp-auth.md" in agents
    assert "docs/doctoring/figma-cloud-agent-mcp-auth.md" in master
