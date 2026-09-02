#!/usr/bin/env python3
"""EgressWeave-backed GitHub REST API opener for the Pingora edge policy.

``scripts/ci/pingora_edge_policy.py`` reimplements a subset of what
`EgressWeave <https://github.com/ContextualWisdomLab/EgressWeave>`_ already
does for its own outbound GitHub REST API calls: an ``api.github.com``-only
origin pin (``_validate_github_api_url``), redirect rejection
(``NoRedirectHandler``), and a bounded response read
(``MAX_RESPONSE_BYTES = 16_777_216``). This module is the prepared,
EgressWeave-backed replacement for that logic — see
``docs/adr/0021-pingora-edge-policy-egressweave-migration.md`` for the design
and ``vendor/egressweave`` (a git submodule pinned to an exact reviewed
commit, per that ADR and EgressWeave's own
``docs/adr/0005-cwl-central-github-ci-consumer-integration.md``) for the
vendored dependency.

``github_open_json`` implements the exact ``(url, token) -> object`` shape
``pingora_edge_policy.py``'s ``OpenJson`` callable expects, so it is a
drop-in replacement for that module's ``_github_open_json`` once wired in.
This module does not itself change ``pingora_edge_policy.py``'s live default
behavior: it is an additive, independently tested unit landed ahead of that
cutover, per this organization's "prove the pattern before the rip-and-
replace" migration convention for security-relevant changes.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

_VENDOR_SRC = Path(__file__).resolve().parents[2] / "vendor" / "egressweave" / "src"
sys.path.insert(0, str(_VENDOR_SRC))

import httpx  # noqa: E402
from egressweave import (  # noqa: E402
    EgressNotAllowedError,
    EgressPolicy,
    build_egress_sync_client,
)

GITHUB_API_HOSTNAME = "api.github.com"
GITHUB_API_ORIGIN = f"https://{GITHUB_API_HOSTNAME}"

# GET-only: every current pingora_edge_policy.py call site only reads GitHub
# changed-file and contents evidence. Narrowing the allowlist below
# EgressPolicy's own broader default method set is a deliberate least-
# privilege choice for this specific read-only consumer.
_POLICY = EgressPolicy.from_hosts(GITHUB_API_HOSTNAME, allowed_methods={"GET"})


class EgressAdapterError(RuntimeError):
    """Raised when a trusted, parsed JSON document cannot be returned.

    Covers malformed or non-GitHub-API URLs, pinned-client construction and
    policy failures, HTTP transport/status failures, and malformed response
    JSON so callers receive one stable adapter-boundary failure type.
    """


_client: httpx.Client | None = None


def _build_client() -> httpx.Client:
    """Build one EgressWeave-pinned ``httpx.Client`` for ``api.github.com``.

    The returned client's transport is pinned to ``api.github.com``'s
    validated addresses, rejects redirects and environment proxies, and
    bounds the response body to ``_POLICY.max_response_bytes`` (16 MiB by
    default, matching ``pingora_edge_policy.py``'s own
    ``MAX_RESPONSE_BYTES``) — see EgressWeave's ``AGENTS.md`` invariants.
    """
    _, client = build_egress_sync_client(GITHUB_API_ORIGIN, policy=_POLICY)
    return client


def _default_client() -> httpx.Client:
    """Return the process-wide pinned GitHub API client, building it lazily."""
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def _validate_github_api_url(url: str) -> None:
    """Fail closed unless ``url`` is a syntactically valid GitHub API URL."""
    try:
        parsed = urlsplit(url)
        hostname = parsed.hostname
    except (TypeError, ValueError) as exc:
        raise EgressAdapterError("refusing to open a malformed GitHub API URL") from exc
    if parsed.scheme != "https" or hostname != GITHUB_API_HOSTNAME:
        raise EgressAdapterError(f"refusing to open a non-GitHub-API URL: {url!r}")


def github_open_json(url: str, token: str) -> object:
    """Fetch one bounded GitHub REST JSON document via the pinned client.

    ``url`` must be a syntactically valid ``https://api.github.com/...`` URL.
    Destination authority, redirect, proxy, DNS-rebinding, and oversized-body
    controls remain owned by the EgressWeave client constructed internally;
    callers cannot inject an alternate transport into this public boundary.
    ``token`` is sent as a ``Bearer`` credential and must be non-empty.

    Raises :class:`EgressAdapterError` for malformed/untrusted URLs, client
    construction or policy failure, HTTP transport/status failure, or a
    response body that is not valid JSON.
    """
    if not token:
        raise EgressAdapterError("a GitHub token is required")
    _validate_github_api_url(url)

    try:
        active_client = _default_client()
    except Exception as exc:
        raise EgressAdapterError(
            f"failed to construct pinned GitHub API client: {type(exc).__name__}"
        ) from exc

    try:
        response = active_client.get(
            url,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "cwl-pingora-edge-egress-opener/1",
            },
        )
        response.raise_for_status()
    except EgressNotAllowedError as exc:
        raise EgressAdapterError("EgressWeave denied the GitHub API request") from exc
    except httpx.HTTPStatusError as exc:
        raise EgressAdapterError(
            f"GitHub API request failed with status {exc.response.status_code}"
        ) from exc
    except httpx.HTTPError as exc:
        raise EgressAdapterError(
            f"GitHub API request failed: {type(exc).__name__}"
        ) from exc
    except Exception as exc:
        raise EgressAdapterError(
            f"GitHub API client failed: {type(exc).__name__}"
        ) from exc

    try:
        return response.json()
    except ValueError as exc:
        raise EgressAdapterError("GitHub API returned malformed JSON") from exc
