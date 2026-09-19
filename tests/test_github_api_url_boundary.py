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
    "file:///etc/passwd",
)


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
