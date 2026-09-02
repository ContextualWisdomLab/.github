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

    Covers a missing token, a non-GitHub-API URL, an EgressWeave policy
    denial, a non-2xx GitHub response, and a GitHub response that is not
    valid JSON — mirroring the single generic failure mode
    ``pingora_edge_policy.py``'s own ``PolicyError`` provides today.
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


def github_open_json(url: str, token: str, *, client: object | None = None) -> object:
    """Fetch one bounded GitHub REST JSON document via the pinned client.

    ``url`` must be an ``https://api.github.com/...`` URL; every other
    destination authority, redirect, and oversized-response protection is
    enforced by the injected EgressWeave policy rather than reimplemented
    here. ``token`` is sent as a ``Bearer`` credential and must be non-empty.
    ``client`` defaults to the module's lazily-built, process-wide pinned
    ``httpx.Client``; tests inject a fake exposing a compatible
    ``get(url, *, headers) -> response`` method instead of exercising real
    network I/O. The returned response must expose ``raise_for_status()``
    and ``json()`` the way ``httpx.Response`` does.

    Raises :class:`EgressAdapterError` for a missing token, a non-GitHub-API
    URL, an EgressWeave policy denial, a non-2xx HTTP status, or a response
    body that is not valid JSON. Never raises any other exception type.
    """
    if not token:
        raise EgressAdapterError("a GitHub token is required")
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != GITHUB_API_HOSTNAME:
        raise EgressAdapterError(f"refusing to open a non-GitHub-API URL: {url!r}")
    active_client = _default_client() if client is None else client
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
    try:
        return response.json()
    except ValueError as exc:
        raise EgressAdapterError("GitHub API returned malformed JSON") from exc
