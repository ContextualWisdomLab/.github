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
   — the exact list of OpenRouter endpoints served under a zero-data-retention
   policy. It is not an upstream-routing restriction; exact model identity, or
   one unambiguous final model component, can inform another provider row.
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


OPENROUTER_ZDR_ENDPOINTS_SOURCE = "https://openrouter.ai/api/v1/endpoints/zdr"


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
        openrouter_endpoints_feed: When True, this provider has no static
            fallback and requires model-level feed evidence.
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
    "nvidia_nim": ProviderZdrScope(
        provider_name="nvidia_nim",
        zero_data_retention=False,
        source="https://openrouter.ai/docs/guides/privacy/provider-logging",
        as_of="2026-08-27",
        note="Direct NVIDIA NIM hosted API (integrate.api.nvidia.com) is not "
        "attested as zero-retention; treat as retained unless a dated provider "
        "attestation is added.",
    ),
    "nvidia_nim_sub": ProviderZdrScope(
        provider_name="nvidia_nim_sub",
        zero_data_retention=False,
        source="https://openrouter.ai/docs/guides/privacy/provider-logging",
        as_of="2026-08-27",
        note="Secondary NVIDIA NIM key shares the nvidia_nim scope and is not "
        "attested as zero-retention.",
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


def _feed_model_ids(zdr_endpoints: frozenset[str]) -> frozenset[str]:
    """Extract normalized model identities from canonical OpenRouter evidence keys."""
    return frozenset(
        key.split("/", 1)[1].strip().casefold()
        for key in zdr_endpoints
        if (
            isinstance(key, str)
            and key.casefold().startswith("openrouter/")
            and key.split("/", 1)[1].strip()
        )
    )


def _feed_model_matches(model: str, feed_model_ids: frozenset[str]) -> bool:
    """Match exact ids or one unambiguous final model component."""
    if not isinstance(model, str):
        return False
    normalized = model.strip().lstrip("/").casefold()
    if normalized in feed_model_ids:
        return True
    suffix = normalized.rsplit("/", 1)[-1]
    suffix_matches = {
        candidate
        for candidate in feed_model_ids
        if candidate.rsplit("/", 1)[-1] == suffix
    }
    return bool(suffix) and len(suffix_matches) == 1


def is_zdr_model(
    provider_name: str,
    *,
    model: str | None = None,
    zdr_endpoints: frozenset[str] = frozenset(),
) -> bool:
    """Decide whether one discovered model route is ZDR-compliant.

    Args:
        provider_name: Orchestrator provider identifier of the model route.
        model: Specific model or route identifier. OpenRouter rows require
            exact route membership; matching model identity, including one
            unambiguous final-component match, can provide evidence for other
            configured providers.
        zdr_endpoints: Frozen set of ``\"provider/model\"`` keys from the
            OpenRouter ``/api/v1/endpoints/zdr`` feed. An empty set never
            grants feed-based ZDR.

    Returns:
        True only for an attested zero-retention scope or an exact/unambiguous
        feed model-identity match.
    """
    scope = provider_zdr_scope(provider_name)
    if scope.openrouter_endpoints_feed:
        if not zdr_endpoints or not model:
            return False
        return route_key(provider_name, model) in zdr_endpoints
    if model and zdr_endpoints and _feed_model_matches(model, _feed_model_ids(zdr_endpoints)):
        return True
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
