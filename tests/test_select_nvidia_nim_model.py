"""Tests for resolving a live NVIDIA NIM model from an ordered candidate pool."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any

import pytest

from scripts.ci import select_nvidia_nim_model as resolver


class _FakeResponse(io.BytesIO):
    """Minimal context-managed HTTP response body for catalog stubs."""

    def __enter__(self) -> "_FakeResponse":
        """Return the response itself, matching urlopen's context manager."""
        return self

    def __exit__(self, *_exc_info: object) -> bool:
        """Close the buffer and never suppress an exception."""
        self.close()
        return False


def _catalog(*model_ids: str) -> bytes:
    """Render an OpenAI-compatible model catalog payload for the given ids."""
    return json.dumps({"object": "list", "data": [{"id": model_id} for model_id in model_ids]}).encode("utf-8")


def _stub_catalog(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[Any]:
    """Serve one canned catalog payload and record the issued requests."""
    requests: list[Any] = []

    def fake_urlopen(request: Any, timeout: float | None = None) -> _FakeResponse:
        """Return the canned catalog and record request security metadata."""
        requests.append((request, timeout))
        return _FakeResponse(payload)

    monkeypatch.setattr(resolver.urllib.request, "urlopen", fake_urlopen)
    return requests


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
    request, timeout = requests[0]
    assert request.full_url == f"{resolver.DEFAULT_BASE_URL}/models"
    assert request.get_header("Authorization") == "Bearer secret-key"
    assert timeout == 7.0


def test_fetch_served_model_ids_ignores_malformed_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Entries without a usable string id cannot become selectable models."""
    payload = json.dumps({"data": [{"id": ""}, {"id": 7}, "not-an-object", {"id": "a/one"}]}).encode("utf-8")
    _stub_catalog(monkeypatch, payload)

    assert resolver.fetch_served_model_ids(resolver.DEFAULT_BASE_URL, "secret-key") == {"a/one"}


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            urllib.error.HTTPError(url="https://x.invalid", code=401, msg="no", hdrs=None, fp=None),
            "HTTP 401",
        ),
        (urllib.error.URLError("dns"), "unreachable"),
    ],
)
def test_fetch_served_model_ids_fails_closed_on_transport_errors(
    monkeypatch: pytest.MonkeyPatch, error: Exception, message: str
) -> None:
    """A catalog outage is reported, never masked by guessing a model id."""

    def fake_urlopen(_request: Any, timeout: float | None = None) -> _FakeResponse:
        """Raise the configured provider failure from the HTTP boundary."""
        raise error

    monkeypatch.setattr(resolver.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match=message):
        resolver.fetch_served_model_ids(resolver.DEFAULT_BASE_URL, "secret-key")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"<html>maintenance</html>", "non-JSON body"),
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

    assert resolver.main(["--candidates", "retired/model"]) == 1
    assert "::error::no configured primary NVIDIA NIM model candidate" in capsys.readouterr().err
