"""Credential-egress contract for GHAS configuration-identity HTTP redirects."""

from __future__ import annotations

from email.message import Message
import urllib.request

import pytest

from scripts.ci import codeql_ghas_configuration_identity as identity


def _redirect_headers(location: str) -> Message:
    """Build the header shape urllib passes to ``redirect_request``."""
    headers = Message()
    headers["Location"] = location
    return headers


def test_github_api_redirect_handler_rejects_external_origin_before_forwarding_bearer():
    """An admitted GitHub API request must not redirect its bearer token off-origin."""
    request = urllib.request.Request(
        "https://api.github.com/repos/ContextualWisdomLab/.github/code-scanning/analyses",
        headers={"Authorization": "Bearer sentinel-secret"},
        method="GET",
    )
    handler = identity._GitHubApiRedirectHandler()

    with pytest.raises(identity.ConfigurationIdentityError, match="api.github.com"):
        handler.redirect_request(
            request,
            None,
            302,
            "Found",
            _redirect_headers("https://evil.example/capture"),
            "https://evil.example/capture",
        )


def test_github_api_redirect_handler_preserves_same_origin_redirects():
    """Legitimate GitHub API redirects remain usable without weakening the origin boundary."""
    request = urllib.request.Request(
        "https://api.github.com/repos/ContextualWisdomLab/.github/code-scanning/analyses",
        headers={"Authorization": "Bearer sentinel-secret"},
        method="GET",
    )
    handler = identity._GitHubApiRedirectHandler()

    redirected = handler.redirect_request(
        request,
        None,
        302,
        "Found",
        _redirect_headers("https://api.github.com/repositories/123/code-scanning/analyses"),
        "https://api.github.com/repositories/123/code-scanning/analyses",
    )

    assert redirected is not None
    assert redirected.full_url == "https://api.github.com/repositories/123/code-scanning/analyses"
    assert redirected.get_header("Authorization") == "Bearer sentinel-secret"
