"""Organizational zero-data-retention (ZDR) provider policy for CI review routing.

ZDR is defined here the way OpenRouter defines it: a provider "will not store
your data for any period of time", and endpoints with zero retention are also
unable to train on the data (OpenRouter, 2026, Zero data retention,
https://openrouter.ai/docs/guides/features/zdr). The policy is deliberately
conservative: any provider whose zero-retention guarantee cannot be attested
from a machine-readable, dated source is treated as NOT ZDR, following
OpenRouter's own stance that "if OpenRouter is not able to establish or
ascertain a clear policy for a provider or endpoint, we take a conservative
stance and assume that the endpoint both retains and trains on data".

Two authoritative, machine-readable sources feed the policy at runtime:

1. OpenRouter ZDR endpoint feed (``https://openrouter.ai/api/v1/endpoints/zdr``)
   — the exact list of model endpoints OpenRouter serves under a zero-data-
   retention policy. Used verbatim for the ``openrouter`` provider scope.
2. OpenRouter provider data-policy catalog
   (``https://openrouter.ai/api/frontend/v1/all-providers``) — per-provider
   ``dataPolicy`` (``retainsPrompts`` / ``retentionDays`` / ``training``),
   consulted and frozen into this module's ``PROVIDER_ZDR_SCOPE`` attestation
   table as-of the date recorded on each entry.

This module is stdlib-only so the whole policy can run and be tested offline;
the runtime ZDR feed is merged in by
``scripts/ci/contextual_orchestrator_review_policy.py``.
"""

from __future__ import annotations

import dataclasses
import re
from typing import Mapping


@dataclasses.dataclass(frozen=True)
class ProviderZdrScope:
    """One provider's ZDR attestation for the CI review sidecar.

    Attributes:
        provider_name: Orchestrator provider identifier (openrouter, nvidia_nim,
            nvidia_nim_sub, bytez, openai).
        zero_data_retention: True only when a zero-retention guarantee for the
            given scope is attested by an authoritative, dated source.
        source: URL or document that grounds the attestation.
        as_of: ISO date the attestation was last verified.
        note: One-sentence scope note; never fabricated policy language.
        openrouter_endpoints_feed: When True, the authoritative OpenRouter
            ``/api/v1/endpoints/zdr`` feed decides per-model ZDR membership for
            this provider; the static table is then only the fallback.
    """

    provider_name: str
    zero_data_retention: bool
    source: str
    as_of: str
    note: str
    openrouter_endpoints_feed: bool = False


PROVIDER_ZDR_SCOPE: Mapping[str, ProviderZdrScope] = {
    "openrouter": ProviderZdrScope(
        provider_name="openrouter",
        zero_data_retention=True,
        source="https://openrouter.ai/docs/guides/features/zdr",
        as_of="2026-08-27",
        note="OpenRouter itself retains no prompts unless prompt logging is "
        "explicitly opted into; the /api/v1/endpoints/zdr feed is the "
        "authoritative per-endpoint membership source.",
        openrouter_endpoints_feed=True,
    ),
    # Full citation for the two NVIDIA entries below: NVIDIA's own current
    # *NVIDIA API Trial Terms of Service* (v. September 19, 2025 -- the terms
    # governing this org's free/trial integrate.api.nvidia.com key; confirmed
    # still the live document as of the as_of date on these entries), Section
    # 3.3(iv), states NVIDIA collects "User Content and Generated Content to
    # improve NVIDIA products and services, including AI models" -- i.e.
    # prompts and completions ARE used for training. This is not merely an
    # absence of attestation; it is an affirmative not-ZDR fact. Section 2.3's
    # "will not store or use User Content or Generated Content at the end of
    # each API Service session" does not override this: 3.3 is the operative
    # carve-out. Do not reclassify either provider as ZDR without a
    # superseding, dated NVIDIA document that repeals or narrows Section
    # 3.3(iv) for this specific API Service.
    "nvidia_nim": ProviderZdrScope(
        provider_name="nvidia_nim",
        zero_data_retention=False,
        source="https://assets.ngc.nvidia.com/products/api-catalog/legal/"
        "NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf",
        as_of="2026-08-30",
        note="NVIDIA API Trial Terms of Service Section 3.3(iv) states User "
        "Content and Generated Content are used to improve NVIDIA products "
        "and services, including AI models -- affirmatively not ZDR.",
    ),
    "nvidia_nim_sub": ProviderZdrScope(
        provider_name="nvidia_nim_sub",
        zero_data_retention=False,
        source="https://assets.ngc.nvidia.com/products/api-catalog/legal/"
        "NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf",
        as_of="2026-08-30",
        note="Secondary NVIDIA NIM key is the same integrate.api.nvidia.com "
        "trial API and shares the nvidia_nim entry's Section 3.3(iv) "
        "training-use scope verbatim.",
    ),
    "openai": ProviderZdrScope(
        provider_name="openai",
        zero_data_retention=False,
        source="https://openrouter.ai/docs/guides/privacy/provider-logging",
        as_of="2026-08-27",
        note="Default OpenAI API scope is not zero-retention (abuse-monitoring "
        "retention windows apply unless a contractual ZDR program is in place).",
    ),
    "bytez": ProviderZdrScope(
        provider_name="bytez",
        zero_data_retention=False,
        source="https://openrouter.ai/docs/guides/features/zdr",
        as_of="2026-08-27",
        note="Bytez retention policy is not attested; conservative default is "
        "retained/trains per OpenRouter's stance on unascertained policies.",
    ),
}


PROVIDER_CREDENTIAL_NAMES: Mapping[str, str] = {
    "bytez": "BYTEZ_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
    "nvidia_nim_sub": "NVIDIA_NIM_API_KEY_SUB",
    "openrouter": "OPENROUTER_API_KEY",
    "openai": "OPENAI_API_KEY",
}


PROVIDER_BASE_URLS: Mapping[str, str] = {
    "bytez": "https://api.bytez.com/models/v2/openai/v1",
    "nvidia_nim": "https://integrate.api.nvidia.com/v1",
    "nvidia_nim_sub": "https://integrate.api.nvidia.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "openai": "https://api.openai.com/v1",
}


PROVIDER_AUTH_SCHEMES: Mapping[str, str] = {
    "bytez": "Key",
    "nvidia_nim": "Bearer",
    "nvidia_nim_sub": "Bearer",
    "openrouter": "Bearer",
    "openai": "Bearer",
}


_PROVIDER_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def provider_zdr_scope(provider_name: str) -> ProviderZdrScope:
    """Return the ZDR scope for a provider, failing fast on unknown names.

    Args:
        provider_name: Orchestrator provider identifier; must be present in
            ``PROVIDER_ZDR_SCOPE``.

    Returns:
        The provider's frozen ``ProviderZdrScope`` attestation.

    Raises:
        KeyError: If the provider is not in the policy table, so a catalog
            writer cannot silently route around an unattested provider.
    """
    return PROVIDER_ZDR_SCOPE[provider_name]


def known_provider_names() -> tuple[str, ...]:
    """Return the sorted provider identifiers recognized by this policy."""
    return tuple(sorted(PROVIDER_ZDR_SCOPE))


def route_key(provider_name: str, model: str) -> str:
    """Return the ``provider/model`` key used for exact ZDR membership.

    Args:
        provider_name: Orchestrator or feed provider identifier.
        model: Discovered or feed model identifier.

    Returns:
        A ``provider/model`` route key with a leading slash stripped from
        ``model``.
    """
    return f"{provider_name}/{model.strip().lstrip('/')}"


def is_zdr_model(
    provider_name: str,
    *,
    model: str | None = None,
    zdr_endpoints: frozenset[str] = frozenset(),
) -> bool:
    """Decide whether one discovered model route is ZDR-compliant.

    Args:
        provider_name: Orchestrator provider identifier of the model route.
        model: Specific model or route identifier. Required for an exact
            OpenRouter feed match; omitted or empty never grants ZDR from
            the feed.
        zdr_endpoints: Frozen set of exact ``\"provider/model\"`` route keys
            from the OpenRouter ``/api/v1/endpoints/zdr`` feed. When the
            provider uses the feed, an empty set is not a fallback to
            \"all OpenRouter is ZDR\".

    Returns:
        True only for an attested zero-retention scope or an exact feed
        membership match.
    """
    scope = provider_zdr_scope(provider_name)
    if scope.openrouter_endpoints_feed:
        if not zdr_endpoints or not model:
            return False
        return route_key(provider_name, model) in zdr_endpoints
    return scope.zero_data_retention


def is_free_route(is_free: object) -> bool:
    """Normalize a discovery ``is_free`` value to a strict boolean.

    Args:
        is_free: Discovery value (bool, int, or string); only truthy boolean
            and numeric values count; string ``\"false\"`` must not be truthy.

    Returns:
        True only for an explicitly truthy free marker.
    """
    if isinstance(is_free, str):
        return is_free.strip().lower() in {"1", "true", "yes"}
    return bool(is_free)