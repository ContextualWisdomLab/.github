"""Canonical authority validation for central CI GitHub REST clients."""

from __future__ import annotations

from urllib.parse import urlsplit


GITHUB_API_AUTHORITY = "api.github.com"


def require_github_api_https_url(url: str) -> str:
    """Return ``url`` only when it uses canonical HTTPS GitHub API authority."""
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError("GitHub API URL must use canonical https://api.github.com authority") from exc
    if (
        parsed.scheme != "https"
        or parsed.netloc != GITHUB_API_AUTHORITY
        or not parsed.path.startswith("/")
        or parsed.fragment
    ):
        raise ValueError("GitHub API URL must use canonical https://api.github.com authority")
    return url
