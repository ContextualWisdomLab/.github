"""Fail-closed redirect contract for authenticated Strix GitHub API reads."""

from __future__ import annotations

from urllib.request import Request

import pytest

from scripts.ci import strix_evidence_binding as binding


def _authenticated_request() -> Request:
    """Build one admitted GitHub REST request carrying a bearer credential."""

    return Request(
        "https://api.github.com/repos/ContextualWisdomLab/example/pulls/1/files",
        headers={"Authorization": "Bearer secret"},
        method="GET",
    )


def test_authenticated_redirect_rejects_cross_origin_before_bearer_forwarding() -> None:
    """A 30x target outside api.github.com must fail before Request creation."""

    handler = binding._GitHubApiRedirectHandler()
    with pytest.raises(binding.EvidenceBindingError, match="only https://api.github.com"):
        handler.redirect_request(
            _authenticated_request(),
            None,
            302,
            "Found",
            {},
            "https://evil.example/collect",
        )


def test_authenticated_redirect_preserves_same_origin_request() -> None:
    """An admitted same-origin redirect keeps the authenticated GitHub request."""

    handler = binding._GitHubApiRedirectHandler()
    redirected = handler.redirect_request(
        _authenticated_request(),
        None,
        302,
        "Found",
        {},
        "/repositories/1/pulls/1/files?page=2",
    )

    assert redirected is not None
    assert redirected.full_url == "https://api.github.com/repositories/1/pulls/1/files?page=2"
    assert redirected.get_header("Authorization") == "Bearer secret"
