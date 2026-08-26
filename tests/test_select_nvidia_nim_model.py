"""Tests for resolving a live NVIDIA NIM model from an ordered candidate pool."""

from __future__ import annotations

import io
import http.client
import json
from pathlib import Path
import ssl
from typing import Any

import pytest

from scripts.ci import select_nvidia_nim_model as resolver


class _FakeResponse(io.BytesIO):
    """Minimal context-managed HTTP response body for catalog stubs."""

    status = 200

    def __enter__(self) -> "_FakeResponse":
        """Return the response itself, matching urlopen's context manager."""
        return self

    def __exit__(self, *_exc_info: object) -> bool:
        """Close the buffer and never suppress an exception."""
        self.close()
        return False


class _FakeConnection:
    """Minimal non-context-managed HTTPS connection stub for catalog requests."""

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout: float,
        context: ssl.SSLContext,
        response: _FakeResponse,
        requests: list[Any],
    ) -> None:
        """Record the validated destination and canned response."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.response = response
        self.requests = requests
        self.closed = False

    def close(self) -> None:
        """Record explicit cleanup, matching ``HTTPSConnection.close``."""
        self.closed = True

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        """Record one outbound request without opening a network socket."""
        self.requests.append((self, method, path, headers))

    def getresponse(self) -> _FakeResponse:
        """Return the canned provider response."""
        return self.response


def _catalog(*model_ids: str) -> bytes:
    """Render an OpenAI-compatible model catalog payload for the given ids."""
    return json.dumps({"object": "list", "data": [{"id": model_id} for model_id in model_ids]}).encode("utf-8")


def _stub_catalog(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[Any]:
    """Serve one canned catalog payload and record the issued requests."""
    requests: list[Any] = []

    def fake_connection(
        host: str, port: int, *, timeout: float, context: ssl.SSLContext
    ) -> _FakeConnection:
        """Return a canned HTTPS connection and record its destination."""
        return _FakeConnection(
            host,
            port,
            timeout=timeout,
            context=context,
            response=_FakeResponse(payload),
            requests=requests,
        )

    monkeypatch.setattr(resolver.http.client, "HTTPSConnection", fake_connection)
    return requests


def test_catalog_sink_has_one_scoped_semgrep_exception_and_explicit_tls() -> None:
    """Keep the reviewed HTTPS sink suppressed only for its known false positive."""
    source_text = Path(resolver.__file__).read_text(encoding="utf-8")
    rule = "python.lang.security.audit.httpsconnection-detected.httpsconnection-detected"
    sink_lines = [
        line for line in source_text.splitlines() if "http.client.HTTPSConnection(" in line
    ]

    assert len(sink_lines) == 1
    assert f"# nosemgrep: {rule}" in sink_lines[0]
    assert source_text.count(f"# nosemgrep: {rule}") == 1
    assert "context=ssl.create_default_context()" in source_text


def test_parse_candidates_keeps_preference_order_without_duplicates() -> None:
    """Operators may concatenate pools; order wins and repeats are dropped."""
    assert resolver.parse_candidates(" a/one\n b/two  a/one ") == ["a/one", "b/two"]
    assert resolver.parse_candidates("   ") == []


@pytest.mark.parametrize(
    ("base_url", "message"),
    [
        ("http://integrate.api.nvidia.com/v1", "must use https"),
        ("https://models.example.invalid/v1", "host is not allowed"),
        ("https://integrate.api.nvidia.com:8443/v1", "default HTTPS port"),
        ("https://user:pass@integrate.api.nvidia.com/v1", "must not embed credentials"),
        ("https://integrate.api.nvidia.com/v1?mode=models", "query or fragment"),
        ("https://integrate.api.nvidia.com/v1#models", "query or fragment"),
    ],
)
def test_validate_catalog_base_url_refuses_untrusted_endpoints(base_url: str, message: str) -> None:
    """A tampered base URL must never receive the provider API key."""
    with pytest.raises(ValueError, match=message):
        resolver.validate_catalog_base_url(base_url)


def test_validate_catalog_base_url_normalizes_the_trusted_endpoint() -> None:
    """The trusted endpoint is accepted with any trailing slash removed."""
    assert resolver.validate_catalog_base_url(f"{resolver.DEFAULT_BASE_URL}/") == resolver.DEFAULT_BASE_URL


def test_fetch_served_model_ids_returns_the_live_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """The resolver reads ids from the provider's OpenAI-compatible catalog."""
    requests = _stub_catalog(monkeypatch, _catalog("a/one", "b/two"))

    served = resolver.fetch_served_model_ids(resolver.DEFAULT_BASE_URL, "secret-key", timeout_seconds=7.0)

    assert served == {"a/one", "b/two"}
    connection, method, path, headers = requests[0]
    assert connection.host == "integrate.api.nvidia.com"
    assert connection.port == 443
    assert connection.timeout == 7.0
    assert connection.context.verify_mode == ssl.CERT_REQUIRED
    assert connection.context.check_hostname is True
    assert connection.closed is True
    assert method == "GET"
    assert path == "/v1/models"
    assert headers["Authorization"] == "Bearer secret-key"


def test_fetch_served_model_ids_ignores_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entries without a usable string id cannot become selectable models."""
    payload = json.dumps({"data": [{"id": ""}, {"id": 7}, "not-an-object", {"id": "a/one"}]}).encode("utf-8")
    _stub_catalog(monkeypatch, payload)

    assert resolver.fetch_served_model_ids(resolver.DEFAULT_BASE_URL, "secret-key") == {"a/one"}


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (http.client.RemoteDisconnected("closed"), "unreachable"),
        (OSError("dns"), "unreachable"),
    ],
)
def test_fetch_served_model_ids_fails_closed_on_transport_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    """A catalog outage is reported, never masked by guessing a model id."""

    def fake_connection(
        _host: str, _port: int, *, timeout: float, context: ssl.SSLContext
    ) -> _FakeConnection:
        """Raise the configured provider failure from the HTTP boundary."""
        del timeout
        del context
        raise error

    monkeypatch.setattr(resolver.http.client, "HTTPSConnection", fake_connection)

    with pytest.raises(RuntimeError, match=message):
        resolver.fetch_served_model_ids(resolver.DEFAULT_BASE_URL, "secret-key")


@pytest.mark.parametrize(
    ("status", "error_type"),
    [
        (401, RuntimeError),
        (429, resolver.ModelResolutionUnavailable),
        (503, resolver.ModelResolutionUnavailable),
    ],
)
def test_fetch_served_model_ids_reports_http_status(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    error_type: type[RuntimeError],
) -> None:
    """Provider HTTP failures identify the status without exposing credentials."""
    response = _FakeResponse(b"{}")
    response.status = status

    def fake_connection(
        _host: str, _port: int, *, timeout: float, context: ssl.SSLContext
    ) -> _FakeConnection:
        """Return an unauthorized provider response."""
        return _FakeConnection(
            "integrate.api.nvidia.com",
            443,
            timeout=timeout,
            context=context,
            response=response,
            requests=[],
        )

    monkeypatch.setattr(resolver.http.client, "HTTPSConnection", fake_connection)

    with pytest.raises(error_type, match=f"HTTP {status}"):
        resolver.fetch_served_model_ids(resolver.DEFAULT_BASE_URL, "secret-key")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"<html>maintenance</html>", "non-JSON body"),
        (b"\x80", "non-JSON body"),
        (b'{"object": "list"}', "no model list"),
        (b'{"data": []}', "no usable model id"),
    ],
)
def test_fetch_served_model_ids_fails_closed_on_unusable_payloads(
    monkeypatch: pytest.MonkeyPatch, payload: bytes, message: str
) -> None:
    """Unparsable or empty catalogs are errors rather than silent fallbacks."""
    _stub_catalog(monkeypatch, payload)

    with pytest.raises(RuntimeError, match=message):
        resolver.fetch_served_model_ids(resolver.DEFAULT_BASE_URL, "secret-key")


def test_select_model_prefers_the_first_served_candidate() -> None:
    """A retired first choice transparently falls through to the next live one."""
    candidates = ["retired/model", "live/model", "other/model"]

    assert resolver.select_model(candidates, {"live/model", "other/model"}, role="primary") == "live/model"


def test_select_model_requires_a_configured_pool() -> None:
    """An empty pool is a configuration error with the role named."""
    with pytest.raises(ValueError, match="no small NVIDIA NIM model candidates"):
        resolver.select_model([], {"live/model"}, role="small")


def test_select_model_reports_a_fully_retired_pool() -> None:
    """When no candidate is served, the message tells the operator what to do."""
    with pytest.raises(RuntimeError, match="Add a live model id to the candidate pool"):
        resolver.select_model(["retired/model"], {"live/model"}, role="primary")


def test_main_prints_the_resolved_model_id(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The successful path prints exactly the resolved id for shell capture."""
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-key")
    _stub_catalog(monkeypatch, _catalog("live/model"))

    exit_code = resolver.main(["--role", "primary", "--candidates", "retired/model live/model"])

    assert exit_code == 0
    assert capsys.readouterr().out == "live/model\n"


def test_main_excludes_the_resolved_primary_from_fallback_selection(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fallback resolution selects a distinct live model from an overlapping pool."""
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-key")
    _stub_catalog(monkeypatch, _catalog("primary/model", "fallback/model"))

    exit_code = resolver.main(
        [
            "--role",
            "fallback",
            "--candidates",
            "primary/model fallback/model",
            "--exclude",
            "primary/model",
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == "fallback/model\n"


def test_main_treats_exclusion_only_empty_pool_as_temporarily_unavailable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A valid pool exhausted by exclusion keeps cross-provider failover available."""
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-key")
    _stub_catalog(monkeypatch, _catalog("primary/model"))

    exit_code = resolver.main(
        [
            "--role",
            "fallback",
            "--candidates",
            "primary/model",
            "--exclude",
            "primary/model",
        ]
    )

    assert exit_code == resolver.EX_TEMPFAIL
    assert "no distinct fallback" in capsys.readouterr().err


def test_main_accepts_the_workflow_secret_name(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Either credential variable name works, so callers need no shim."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "secret-key")
    _stub_catalog(monkeypatch, _catalog("live/model"))

    assert resolver.main(["--candidates", "live/model"]) == 0
    assert capsys.readouterr().out == "live/model\n"


def test_main_requires_a_provider_credential(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Without a credential the resolver fails closed with a CI annotation."""
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)

    assert resolver.main(["--candidates", "live/model"]) == 1
    assert "NVIDIA_API_KEY is required" in capsys.readouterr().err


def test_main_annotates_a_resolution_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Resolution failures surface as GitHub error annotations, not tracebacks."""
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-key")
    _stub_catalog(monkeypatch, _catalog("live/model"))

    assert resolver.main(["--candidates", "retired/model"]) == resolver.EX_TEMPFAIL
    assert "::error::no configured primary NVIDIA NIM model candidate" in capsys.readouterr().err


def test_main_keeps_invalid_operator_configuration_nonrecoverable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty operator pool is invalid rather than provider unavailability."""
    monkeypatch.setenv("NVIDIA_API_KEY", "secret-key")
    _stub_catalog(monkeypatch, _catalog("live/model"))

    assert resolver.main(["--candidates", ""]) == 1
    assert "no primary NVIDIA NIM model candidates" in capsys.readouterr().err


def test_main_keeps_catalog_authentication_errors_nonrecoverable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An invalid provider credential must not silently switch providers."""
    monkeypatch.setenv("NVIDIA_API_KEY", "invalid-key")
    response = _FakeResponse(b"{}")
    response.status = 401

    def fake_connection(
        _host: str, _port: int, *, timeout: float, context: ssl.SSLContext
    ) -> _FakeConnection:
        return _FakeConnection(
            "integrate.api.nvidia.com",
            443,
            timeout=timeout,
            context=context,
            response=response,
            requests=[],
        )

    monkeypatch.setattr(resolver.http.client, "HTTPSConnection", fake_connection)

    assert resolver.main(["--candidates", "live/model"]) == 1
    assert "HTTP 401" in capsys.readouterr().err
