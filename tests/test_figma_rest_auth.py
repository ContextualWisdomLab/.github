"""Contracts for Cloud Agent Figma REST authentication and file load."""

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
ARCHITECTURE = ROOT / "ARCHITECTURE.md"
CHANGELOG = ROOT / "CHANGELOG.md"
TOKEN = "figd_test_token_must_never_appear"
FILE_KEY = "Ab12Cd34"


def _whoami_body(**fields: str) -> bytes:
    """Return a Figma ``/v1/me`` JSON body."""
    return json.dumps(fields).encode("utf-8")


def _file_body(**fields: Any) -> bytes:
    """Return a Figma ``/v1/files/:key`` JSON body."""
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


def test_validate_file_key_rejects_path_injection() -> None:
    """File keys cannot carry slashes, dots, or query characters into the path."""
    for raw in ("", "short", "../passwd", "abc/defgh", "abc.defgh", "abc?depth=1"):
        with pytest.raises(auth.FigmaAuthError) as refused:
            auth.validate_file_key(raw)
        assert refused.value.exit_code == auth.EXIT_TRANSPORT
        assert TOKEN not in str(refused.value)
    assert auth.validate_file_key(f"  {FILE_KEY} \n") == FILE_KEY
    assert auth.file_document_path(FILE_KEY) == f"/v1/files/{FILE_KEY}?depth=1"
    assert auth.file_document_url(FILE_KEY) == (
        f"https://api.figma.com/v1/files/{FILE_KEY}?depth=1"
    )


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
        "Figma REST authentication succeeded."
    )


def test_parse_whoami_payload_rejects_non_objects() -> None:
    """Non-JSON and non-object bodies are transport failures, not auth success."""
    with pytest.raises(auth.FigmaAuthError) as invalid_json:
        auth.parse_whoami_payload(b"not-json")
    assert invalid_json.value.exit_code == auth.EXIT_TRANSPORT
    assert "/v1/me" in str(invalid_json.value)

    with pytest.raises(auth.FigmaAuthError) as not_object:
        auth.parse_whoami_payload(b'["me"]')
    assert not_object.value.exit_code == auth.EXIT_TRANSPORT

    with pytest.raises(auth.FigmaAuthError):
        auth.parse_whoami_payload(b"\xff")

    assert auth.parse_whoami_payload(b'{"handle":"ok"}') == {"handle": "ok"}


def test_verify_rest_auth_accepts_valid_token() -> None:
    """A 200 ``/v1/me`` response is the Cloud Agent auth success signal."""
    seen: dict[str, Any] = {}

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
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
        del url, headers
        return 503, b"unavailable"

    with pytest.raises(auth.FigmaAuthError) as transport:
        auth.verify_rest_auth({auth.TOKEN_ENV_NAME: TOKEN}, opener)
    assert transport.value.exit_code == auth.EXIT_TRANSPORT
    assert "503" in str(transport.value)


def test_file_document_summary_lists_pages_and_token_counts() -> None:
    """A depth=1 file payload becomes a page inventory for the next REST call."""
    summary = auth.file_document_summary(
        FILE_KEY,
        {
            "name": "naruon GNB",
            "version": "42",
            "lastModified": "2026-08-16T00:00:00Z",
            "document": {
                "children": [
                    {"name": "Home"},
                    {"name": "  "},
                    "skip",
                    {"name": "Mail"},
                ]
            },
            "components": {"1:2": {"name": "Button"}},
            "styles": {"3:4": {"name": "Color/Primary"}},
        },
    )
    assert f"key={FILE_KEY}" in summary
    assert "name=naruon GNB" in summary
    assert "pages=Home, Mail" in summary
    assert "components=1" in summary
    assert "styles=1" in summary
    assert TOKEN not in summary
    sparse = auth.file_document_summary(FILE_KEY, {"document": {"children": "nope"}})
    assert "pages=(none)" in sparse
    assert "components=0" in sparse
    assert auth.file_document_summary(FILE_KEY, {}) == (
        f"Figma file loaded (key={FILE_KEY}; pages=(none); components=0; "
        "styles=0). Next: pick a page and request that node or its images over REST."
    )


def test_fetch_file_document_accepts_valid_token() -> None:
    """A 200 ``/v1/files/:key?depth=1`` response is the Cloud Agent file signal."""
    seen: dict[str, Any] = {}

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        seen["url"] = url
        seen["headers"] = dict(headers)
        return 200, _file_body(name="Inkspan", document={"children": [{"name": "Cover"}]})

    summary = auth.fetch_file_document(FILE_KEY, {auth.TOKEN_ENV_NAME: TOKEN}, opener)
    assert seen["url"] == auth.file_document_url(FILE_KEY)
    assert seen["headers"] == {auth.TOKEN_HEADER: TOKEN}
    assert "name=Inkspan" in summary
    assert "pages=Cover" in summary
    assert TOKEN not in summary


def test_fetch_file_document_classifies_auth_and_missing_file() -> None:
    """401/403 rotate the secret; 404 tells the operator to check the file key."""

    def forbidden(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        del url, headers
        return 403, b'{"status":403,"err":"Invalid token"}'

    with pytest.raises(auth.FigmaAuthError) as rejected:
        auth.fetch_file_document(FILE_KEY, {auth.TOKEN_ENV_NAME: TOKEN}, forbidden)
    assert rejected.value.exit_code == auth.EXIT_REJECTED
    assert TOKEN not in str(rejected.value)

    def missing(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        del url, headers
        return 404, b'{"status":404,"err":"Not found"}'

    with pytest.raises(auth.FigmaAuthError) as transport:
        auth.fetch_file_document(FILE_KEY, {auth.TOKEN_ENV_NAME: TOKEN}, missing)
    assert transport.value.exit_code == auth.EXIT_TRANSPORT
    assert "404" in str(transport.value)
    assert "file_content:read" in str(transport.value)


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
    """Record the pinned Figma origin used by ``pinned_https_get``."""

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
        """Record the pinned GET call."""
        self.method = method
        self.path = path
        self.headers = dict(headers or {})

    def getresponse(self) -> _FakeWhoamiResponse:
        """Return the canned whoami response."""
        return _FakeWhoamiResponse(self._status, self._body)

    def close(self) -> None:
        """Mark the connection closed."""
        self.closed = True


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


def test_pinned_https_get_rejects_unsafe_paths() -> None:
    """Only ``/v1/`` paths without traversal characters reach the TLS sink."""
    headers = {auth.TOKEN_HEADER: TOKEN}
    with pytest.raises(auth.FigmaAuthError) as scheme:
        auth.pinned_https_get("file:///etc/passwd", headers, 16)
    assert " /v1/" in str(scheme.value) or "/v1/" in str(scheme.value)
    with pytest.raises(auth.FigmaAuthError) as traversal:
        auth.pinned_https_get("/v1/../etc/passwd", headers, 16)
    assert traversal.value.exit_code == auth.EXIT_TRANSPORT
    with pytest.raises(auth.FigmaAuthError) as spaced:
        auth.pinned_https_get("/v1/files/a b", headers, 16)
    assert spaced.value.exit_code == auth.EXIT_TRANSPORT
    with pytest.raises(auth.FigmaAuthError) as slash:
        auth.pinned_https_get("/v1/files/a\\b", headers, 16)
    assert slash.value.exit_code == auth.EXIT_TRANSPORT


def test_default_opener_rejects_non_whoami_urls() -> None:
    """``file://`` and other caller URLs never reach the TLS sink."""
    with pytest.raises(auth.FigmaAuthError) as refused:
        auth.default_opener("file:///etc/passwd", {auth.TOKEN_HEADER: TOKEN})
    assert refused.value.exit_code == auth.EXIT_TRANSPORT
    assert "refuses" in str(refused.value)
    assert TOKEN not in str(refused.value)


def test_default_file_opener_rejects_non_file_urls() -> None:
    """File loads accept only the pinned ``depth=1`` HTTPS URL."""
    with pytest.raises(auth.FigmaAuthError) as refused:
        auth.default_file_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert refused.value.exit_code == auth.EXIT_TRANSPORT
    assert "depth=1" in str(refused.value)


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


def test_default_file_opener_reads_success_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful file GET uses the validated key and ``depth=1`` query."""

    class FileConnection(_FakeWhoamiConnection):
        """Return a canned file document from the pinned origin."""

        def __init__(self, host: str, timeout: int = 0) -> None:
            """Initialize a file JSON body."""
            super().__init__(host, timeout)
            self._body = b'{"name":"ok"}'

    monkeypatch.setattr(auth.http.client, "HTTPSConnection", FileConnection)
    status, body = auth.default_file_opener(
        auth.file_document_url(FILE_KEY),
        {auth.TOKEN_HEADER: TOKEN},
    )
    assert status == 200
    assert body == b'{"name":"ok"}'
    connection = FileConnection.last
    assert connection is not None
    assert connection.path == f"/v1/files/{FILE_KEY}?depth=1"
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


def test_helper_pins_https_origin_instead_of_dynamic_urllib() -> None:
    """Semgrep ``dynamic-urllib-use-detected`` must not apply to this helper."""
    source = Path(auth.__file__).read_text(encoding="utf-8")
    assert "urlopen(" not in source
    assert "http.client.HTTPSConnection" in source
    assert '"api.figma.com"' in source
    assert '"/v1/me"' in source
    assert "depth=1" in source


def test_parse_cli_args_accepts_whoami_and_single_file() -> None:
    """The CLI is whoami by default and one ``--file`` key otherwise."""
    assert auth.parse_cli_args([]) == auth.CliRequest(file_key=None)
    assert auth.parse_cli_args(["figma_rest_auth.py"]) == auth.CliRequest(file_key=None)
    assert auth.parse_cli_args(["scripts/ci/figma_rest_auth.py", "--file", FILE_KEY]) == (
        auth.CliRequest(file_key=FILE_KEY)
    )
    assert auth.parse_cli_args(["figma_rest_auth", "--file", FILE_KEY]) == (
        auth.CliRequest(file_key=FILE_KEY)
    )
    with pytest.raises(auth.FigmaAuthError) as usage:
        auth.parse_cli_args(["--file"])
    assert usage.value.exit_code == auth.EXIT_USAGE
    with pytest.raises(auth.FigmaAuthError) as unknown:
        auth.parse_cli_args(["--dump"])
    assert unknown.value.exit_code == auth.EXIT_USAGE
    with pytest.raises(auth.FigmaAuthError) as extra:
        auth.parse_cli_args(["--file", FILE_KEY, "extra"])
    assert extra.value.exit_code == auth.EXIT_USAGE
    with pytest.raises(auth.FigmaAuthError) as bad_key:
        auth.parse_cli_args(["--file", "../passwd"])
    assert bad_key.value.exit_code == auth.EXIT_TRANSPORT


def test_main_writes_identity_and_error_channels() -> None:
    """CLI success and failure stay on stdout/stderr and never echo the token."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
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


def test_main_writes_file_inventory() -> None:
    """``--file`` prints a page inventory and never echoes the token."""
    stdout = io.StringIO()
    stderr = io.StringIO()

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        del headers
        assert url == auth.file_document_url(FILE_KEY)
        return 200, _file_body(name="Wardnet", document={"children": [{"name": "SOC"}]})

    ok = auth.main(
        argv=["--file", FILE_KEY],
        environ={auth.TOKEN_ENV_NAME: TOKEN},
        opener=opener,
        stdout=stdout,
        stderr=stderr,
    )
    assert ok == auth.EXIT_OK
    assert "name=Wardnet" in stdout.getvalue()
    assert "pages=SOC" in stdout.getvalue()
    assert stderr.getvalue() == ""
    assert TOKEN not in stdout.getvalue()


def test_main_uses_process_streams_when_unspecified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default CLI path reads ``os.environ`` and writes process streams."""
    monkeypatch.setenv(auth.TOKEN_ENV_NAME, TOKEN)
    monkeypatch.setattr(auth.sys, "argv", ["figma_rest_auth.py"])

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        del url
        assert headers[auth.TOKEN_HEADER] == TOKEN
        return 200, _whoami_body(id="xyz")

    assert auth.main(opener=opener) == auth.EXIT_OK
    captured = capsys.readouterr()
    assert "id=xyz" in captured.out
    assert TOKEN not in captured.out


def test_live_unauthenticated_whoami_is_rejected_by_figma() -> None:
    """The real ``/v1/me`` endpoint rejects a missing token with HTTP 401/403.

    This is the production accuracy check: Cloud Agents can reach
    ``api.figma.com``, and an absent secret is not treated as MCP success.
    """
    status, body = auth.default_opener(auth.WHOAMI_URL, {})
    assert status in {401, 403}
    assert TOKEN not in body.decode("utf-8", errors="replace")
    lowered = body.lower()
    assert b"token" in lowered or b"unauthorized" in lowered or b"invalid" in lowered


def test_doctoring_and_entry_docs_pin_cloud_agent_fallback() -> None:
    """Agents must not treat Figma MCP OAuth as available in Cloud Agents."""
    doctoring = DOCTORING.read_text(encoding="utf-8")
    agents = AGENTS.read_text(encoding="utf-8")
    master = MASTER.read_text(encoding="utf-8")
    architecture = ARCHITECTURE.read_text(encoding="utf-8")
    changelog = CHANGELOG.read_text(encoding="utf-8")
    for text in (doctoring, agents, master):
        assert "FIGMA_ACCESS_TOKEN" in text
        assert "mcp.figma.com" in text
    assert "X-Figma-Token" in doctoring
    assert "not supported in Cloud agents" in doctoring
    assert "https://api.figma.com/v1/me" in doctoring
    assert "scripts/ci/figma_rest_auth.py" in doctoring
    assert "--file" in doctoring
    assert "depth=1" in doctoring
    assert "plan access token" in doctoring
    assert "Retrieved August 16, 2026" in doctoring
    assert "CWE-22" in doctoring
    assert "RFC 9110" in doctoring
    assert "docs/doctoring/figma-cloud-agent-mcp-auth.md" in agents
    assert "docs/doctoring/figma-cloud-agent-mcp-auth.md" in master
    assert "--file" in agents
    assert "figma_rest_auth.py --file" in master
    assert "Figma REST fallback" in architecture
    assert "depth=1" in architecture
    assert "Figma REST" in changelog
