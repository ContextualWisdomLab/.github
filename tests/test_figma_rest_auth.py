"""Contracts for Cloud Agent Figma REST authentication."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

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

    with pytest.raises(auth.FigmaAuthError) as not_object:
        auth.parse_whoami_payload(b'["me"]')
    assert not_object.value.exit_code == auth.EXIT_TRANSPORT

    with pytest.raises(auth.FigmaAuthError):
        auth.parse_whoami_payload(b"\xff")


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


def test_default_opener_returns_http_error_bodies(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTPError is mapped to ``(status, body)`` so callers can classify 401/403."""

    def fake_urlopen(request: object, timeout: int = 0) -> object:
        del request, timeout
        raise HTTPError(auth.WHOAMI_URL, 403, "Forbidden", hdrs=None, fp=io.BytesIO(b"nope"))

    monkeypatch.setattr(auth.urllib.request, "urlopen", fake_urlopen)
    status, body = auth.default_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert status == 403
    assert body == b"nope"


def test_default_opener_reads_success_body(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful urllib response yields its status and body bytes."""

    class FakeResponse:
        """Minimal urlopen context manager."""

        status = 200

        def read(self) -> bytes:
            """Return a canned body."""
            return b'{"handle":"ok"}'

        def __enter__(self) -> FakeResponse:
            """Return the fake response."""
            return self

        def __exit__(self, *exc: object) -> None:
            """No cleanup."""

    monkeypatch.setattr(auth.urllib.request, "urlopen", lambda *args, **kwargs: FakeResponse())
    status, body = auth.default_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert status == 200
    assert body == b'{"handle":"ok"}'


def test_default_opener_wraps_url_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Network failures become ``EXIT_TRANSPORT`` without leaking the token."""

    def failing_urlopen(request: object, timeout: int = 0) -> object:
        del request, timeout
        raise URLError(reason="timed out")

    monkeypatch.setattr(auth.urllib.request, "urlopen", failing_urlopen)
    with pytest.raises(auth.FigmaAuthError) as transport:
        auth.default_opener(auth.WHOAMI_URL, {auth.TOKEN_HEADER: TOKEN})
    assert transport.value.exit_code == auth.EXIT_TRANSPORT
    assert "timed out" in str(transport.value)
    assert TOKEN not in str(transport.value)


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


def test_main_uses_process_streams_when_unspecified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default CLI path reads ``os.environ`` and writes process streams."""
    monkeypatch.setenv(auth.TOKEN_ENV_NAME, TOKEN)

    def opener(url: str, headers: dict[str, str]) -> tuple[int, bytes]:
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
