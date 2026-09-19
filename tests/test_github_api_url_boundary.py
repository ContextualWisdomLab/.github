"""Fail-closed GitHub REST authority contracts for central CI HTTP clients."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.ci import codeql_ghas_configuration_identity as identity
from scripts.ci import strix_evidence_binding as binding


UNTRUSTED_GITHUB_API_URLS = (
    "http://api.github.com/repos/ContextualWisdomLab/example",
    "https://api.github.com.evil.example/repos/ContextualWisdomLab/example",
    "https://api.github.com@evil.example/repos/ContextualWisdomLab/example",
    "https://api.github.com:443/repos/ContextualWisdomLab/example",
    "https://api.github.com/repos/ContextualWisdomLab/example#fragment",
    "file:///etc/passwd",
)
CANONICAL_GITHUB_API_URL = "https://api.github.com/repos/ContextualWisdomLab/example"


class _JsonResponse:
    """Minimal context-managed JSON response for opener-boundary contracts."""

    def __enter__(self) -> _JsonResponse:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def read(self) -> bytes:
        return b"[]"


def _unexpected_open(*_args: Any, **_kwargs: Any) -> Any:
    """Fail if a rejected authority reaches the network/file opener boundary."""
    pytest.fail("rejected GitHub API authority reached urlopen")


@pytest.mark.parametrize("url", UNTRUSTED_GITHUB_API_URLS)
def test_codeql_identity_client_rejects_noncanonical_github_api_authority(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """CodeQL GHAS reads must reject non-HTTPS or non-api.github.com authorities."""
    monkeypatch.setattr(identity.urllib.request, "urlopen", _unexpected_open)

    with pytest.raises(identity.ConfigurationIdentityError, match="GitHub API URL"):
        identity._request_json(url, token="test-token", timeout_seconds=1)


@pytest.mark.parametrize("url", UNTRUSTED_GITHUB_API_URLS)
def test_strix_evidence_client_rejects_noncanonical_github_api_authority(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """Strix evidence reads must reject non-HTTPS or non-api.github.com authorities."""
    monkeypatch.setattr(binding, "urlopen", _unexpected_open)

    with pytest.raises(binding.EvidenceBindingError, match="GitHub API URL"):
        binding.default_github_opener(url, "test-token")


def test_canonical_github_api_authority_reaches_both_openers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact HTTPS GitHub REST authority remains an allowed production control."""
    identity_calls: list[str] = []
    strix_calls: list[str] = []

    def identity_open(request: Any, **_kwargs: Any) -> _JsonResponse:
        identity_calls.append(request.full_url)
        return _JsonResponse()

    def strix_open(request: Any, **_kwargs: Any) -> _JsonResponse:
        strix_calls.append(request.full_url)
        return _JsonResponse()

    monkeypatch.setattr(identity.urllib.request, "urlopen", identity_open)
    monkeypatch.setattr(binding, "urlopen", strix_open)

    assert identity._request_json(
        CANONICAL_GITHUB_API_URL,
        token="test-token",
        timeout_seconds=1,
    ) == []
    assert binding.default_github_opener(CANONICAL_GITHUB_API_URL, "test-token") == []
    assert identity_calls == [CANONICAL_GITHUB_API_URL]
    assert strix_calls == [CANONICAL_GITHUB_API_URL]
