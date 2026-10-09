"""Fail-closed GitHub REST authority contracts for central CI HTTP clients."""

from __future__ import annotations

from email.message import Message
from io import BytesIO
from typing import Any
from urllib.request import Request, addinfourl

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
REDIRECT_TARGETS = (
    "https://api.github.com/repos/ContextualWisdomLab/redirected",
    "https://api.github.com.evil.example/repos/ContextualWisdomLab/example",
    "http://api.github.com/repos/ContextualWisdomLab/example",
    "file:///etc/passwd",
)
CANONICAL_GITHUB_API_URL = "https://api.github.com/repos/ContextualWisdomLab/example"


class _SyntheticRedirectTransport:
    """Return one synthetic 302 while recording every request reaching transport."""

    def __init__(self, target: str) -> None:
        """Store the redirect target and initialize the observed request ledger."""
        self.target = target
        self.calls: list[tuple[str, str | None]] = []

    def https_open(self, request: Request) -> Any:
        """Return a synthetic redirect response without contacting a network target."""
        self.calls.append((request.full_url, request.get_header("Authorization")))
        headers = Message()
        headers["Location"] = self.target
        response = addinfourl(BytesIO(b""), headers, request.full_url, code=302)
        response.msg = "Found"
        return response


class _JsonResponse:
    """Minimal context-managed JSON response for opener-boundary contracts."""

    def __enter__(self) -> _JsonResponse:
        """Enter the fake response context."""
        return self

    def __exit__(self, *_args: Any) -> None:
        """Leave the fake response context without suppressing exceptions."""
        return None

    def read(self) -> bytes:
        """Return an empty JSON array payload."""
        return b"[]"


def _unexpected_open(*_args: Any, **_kwargs: Any) -> Any:
    """Fail if a rejected authority reaches the network/file opener boundary."""
    pytest.fail("rejected GitHub API authority reached opener")


@pytest.mark.parametrize("url", UNTRUSTED_GITHUB_API_URLS)
def test_codeql_identity_client_rejects_noncanonical_github_api_authority(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """CodeQL GHAS reads must reject non-HTTPS or non-api.github.com authorities."""
    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", _unexpected_open)

    with pytest.raises(identity.ConfigurationIdentityError, match="GitHub API URL"):
        identity._request_json(url, token="test-token", timeout_seconds=1)


@pytest.mark.parametrize("url", UNTRUSTED_GITHUB_API_URLS)
def test_strix_evidence_client_rejects_noncanonical_github_api_authority(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    """Strix evidence reads must reject non-HTTPS or non-api.github.com authorities."""
    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", _unexpected_open)

    with pytest.raises(binding.EvidenceBindingError, match="GitHub API URL"):
        binding.default_github_opener(url, "test-token")


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
@pytest.mark.parametrize("client", ("codeql", "strix"))
def test_production_openers_reject_redirect_without_forwarding_bearer(
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    client: str,
) -> None:
    """Drive a synthetic 302 through each actual opener and forbid a second request."""
    if client == "codeql":
        opener = identity._GITHUB_API_OPENER
        call = lambda: identity._request_json(
            CANONICAL_GITHUB_API_URL,
            token="test-token",
            timeout_seconds=1,
        )
        error_type = identity.ConfigurationIdentityError
    else:
        opener = binding._GITHUB_API_OPENER
        call = lambda: binding.default_github_opener(
            CANONICAL_GITHUB_API_URL,
            "test-token",
        )
        error_type = binding.EvidenceBindingError

    transport = _SyntheticRedirectTransport(target)
    monkeypatch.setitem(
        opener.handle_open,
        "https",
        [transport, *opener.handle_open["https"]],
    )

    with pytest.raises(error_type, match="HTTP 302"):
        call()

    assert transport.calls == [
        (CANONICAL_GITHUB_API_URL, "Bearer test-token"),
    ]


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
def test_codeql_identity_client_never_constructs_redirect_request_with_bearer_token(
    target: str,
) -> None:
    """A GitHub response must not redirect CodeQL credentials to another URL."""
    request = Request(
        CANONICAL_GITHUB_API_URL,
        headers={"Authorization": "Bearer test-token"},
    )
    handler = identity._RejectRedirects()

    redirected = handler.redirect_request(request, None, 302, "Found", {}, target)

    assert redirected is None
    assert request.get_header("Authorization") == "Bearer test-token"


@pytest.mark.parametrize("target", REDIRECT_TARGETS)
def test_strix_evidence_client_never_constructs_redirect_request_with_bearer_token(
    target: str,
) -> None:
    """A GitHub response must not redirect Strix credentials to another URL."""
    request = Request(
        CANONICAL_GITHUB_API_URL,
        headers={"Authorization": "Bearer test-token"},
    )
    handler = binding._RejectRedirects()

    redirected = handler.redirect_request(request, None, 302, "Found", {}, target)

    assert redirected is None
    assert request.get_header("Authorization") == "Bearer test-token"


def test_canonical_github_api_authority_reaches_both_openers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact HTTPS GitHub REST authority remains an allowed production control."""
    identity_calls: list[str] = []
    strix_calls: list[str] = []

    def identity_open(request: Any, **_kwargs: Any) -> _JsonResponse:
        """Record the CodeQL client's validated request URL."""
        identity_calls.append(request.full_url)
        return _JsonResponse()

    def strix_open(request: Any, **_kwargs: Any) -> _JsonResponse:
        """Record the Strix client's validated request URL."""
        strix_calls.append(request.full_url)
        return _JsonResponse()

    monkeypatch.setattr(identity._GITHUB_API_OPENER, "open", identity_open)
    monkeypatch.setattr(binding._GITHUB_API_OPENER, "open", strix_open)

    assert identity._request_json(
        CANONICAL_GITHUB_API_URL,
        token="test-token",
        timeout_seconds=1,
    ) == []
    assert binding.default_github_opener(CANONICAL_GITHUB_API_URL, "test-token") == []
    assert identity_calls == [CANONICAL_GITHUB_API_URL]
    assert strix_calls == [CANONICAL_GITHUB_API_URL]
