"""Build governed contextual-orchestrator review catalogs from discovery evidence.

``orchestrator/free`` remains strictly zero-priced. ``orchestrator/auto`` is
free-first and then uses fully price-attested routes. Models without a complete
price vector remain visible in audit counts but are never admitted to CI review.
Partial, malformed, or contradictory price vectors fail closed.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit, urlunsplit

from scripts.ci.zdr_policy import (
    PROVIDER_AUTH_SCHEMES,
    PROVIDER_BASE_URLS,
    PROVIDER_CREDENTIAL_NAMES,
    is_free_route,
    is_zdr_model,
    provider_zdr_scope,
    route_key,
)

DEFAULT_CATALOG_LIMIT = 12
DEFAULT_ACCOUNT_CAP = 4

_DEFAULT_PORTS: Mapping[str, int] = {"http": 80, "https": 443}

COST_FREE = "free"
COST_PRICED = "priced"
COST_UNKNOWN = "unknown"
_COST_EVIDENCE_RANK: Mapping[str, int] = {
    COST_FREE: 0,
    COST_PRICED: 1,
    COST_UNKNOWN: 2,
}

_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9]*_[a-z0-9]+(?:_[a-z0-9]+)*$")


class PolicyError(ValueError):
    """Raised when discovery evidence cannot produce a governed catalog."""


def provider_account(provider_name: str) -> str:
    """Return the independently credentialed provider account identity."""
    return provider_name


def _outage_domain(row: Mapping[str, Any]) -> str:
    """Return the shared-infrastructure outage domain for a normalized row.

    This is a deliberately *different* axis from :func:`provider_account`.
    ``provider_account`` answers "is this a distinct credential that may be
    entitled to a distinct model catalog" (yes, for ``nvidia_nim`` vs.
    ``nvidia_nim_sub`` -- see PR #941/#945 in ``contextual-orchestrator`` and
    this repo's own matching fix, both of which correctly stopped assuming
    those two independent NVIDIA NIM API keys share a catalog). This
    function instead answers "would one physical upstream outage take both
    of these routes down together" -- and for those same two credentials the
    answer is yes: both resolve to the identical ``base_url``,
    ``https://integrate.api.nvidia.com/v1`` (see ``PROVIDER_BASE_URLS`` in
    ``scripts/ci/zdr_policy.py``, and that table's own ``nvidia_nim_sub``
    ZDR-scope note: "the same integrate.api.nvidia.com trial API").
    Conflating these two axes -- treating "independent credential" as
    "independent outage domain" -- would let two same-endpoint credentials
    jointly report full diversity and jointly fill an admission cap meant to
    protect against exactly one endpoint's outage, silently recreating the
    2026-08-30 ``orchestrator/free`` exhaustion incident this cap exists to
    prevent (see ``docs/product-technical-gap-baseline.md``), just on a
    different axis than the one #941/#945/#1468 already fixed.

    Grouped by each row's own ``base_url`` evidence (already present on
    every row ``parse_discovery_report``/the sidecar's live discovery
    produces) rather than a second hand-maintained provider-name table, so
    this cannot silently go stale independently of the ``base_url`` evidence
    the catalog itself already serves from -- the same failure mode that
    made the removed ``PROVIDER_FAMILIES`` mapping wrong in the first place.

    Compares :func:`_normalize_base_url`'s normalized form, not the raw
    string: two spellings of the identical endpoint (a hostname cased
    differently, an explicit default port, a trailing slash on one row but
    not another) must not be read as two outage domains, or a pure
    formatting accident could reintroduce exactly the diversity-overstating,
    cap-bypassing bug this function exists to fix. Every KV-credentialed
    provider in this codebase today resolves ``base_url`` from one of a
    fixed set of hardcoded string literals (never a live, potentially
    differently-formatted network response), so this normalization changes
    nothing for any input this repository's sidecar currently produces --
    it exists to keep this public, independently invocable function (also
    reachable through this script's own ``--discovery-report`` CLI, not only
    the sidecar's exact generation path) correct for any future input, not
    to compensate for an observed live discrepancy.
    """
    return _normalize_base_url(str(row["base_url"]))


def _normalize_base_url(base_url: str) -> str:
    """Return a case/port/trailing-slash-normalized identity for a base URL.

    Scheme and host are lowercased (both are case-insensitive per RFC 3986
    3.1/3.2.2); an explicit port equal to the scheme's default (``:443`` for
    ``https``, ``:80`` for ``http``) is dropped, since it is equivalent to
    omitting it; exactly one trailing slash is stripped from the path, since
    a base URL's trailing slash does not change which resource it addresses.
    Every other distinction -- a different host, a different non-default
    port, a different path, or a different query string -- is preserved
    verbatim (routing evidence has no legitimate reason to carry a query
    string; preserving rather than dropping it means an unexpected one
    cannot silently vanish from the computed identity). The URL fragment is
    the one deliberate exception: it is stripped, not preserved, because a
    fragment is a client-side-only artifact that is never transmitted to
    the server and therefore never identifies a different upstream endpoint
    -- two base URLs differing only by fragment must collapse to the same
    outage-domain key, sharing one diversity count and one admission-cap
    budget, not report inflated diversity or a separately budgeted cap. Any
    userinfo component present is dropped rather than preserved:
    outage-domain identity is about the physical endpoint, not which
    credential reaches it, and this codebase's base URLs never carry
    userinfo (see ``configured_gateway_source`` in
    ``contextual-orchestrator``, which rejects one outright).

    A string this cannot parse into a scheme, host, and numeric port --
    including an empty string (which would otherwise normalize to a value
    indistinct from a real one-character path), a malformed IPv6 host (an
    unmatched ``[``/``]`` bracket makes ``urlsplit()`` itself raise
    ``ValueError``, before any scheme/host/port is even available to
    inspect), and a non-numeric port substring (``urlsplit(...).port``
    raises ``ValueError`` for one, once splitting succeeds) -- falls back to
    a simple lowercased, stripped copy of the whole string: grouping only
    needs equal inputs to compare equal, not a validated URL, and this
    function must never raise on evidence it merely groups.

    Known, deliberate residual gap: hostname canonicalization stops at
    lowercasing. A trailing root-label dot (``host.``), an IDN written as
    Unicode versus its ASCII/punycode form, or two differently-compressed
    but equivalent literal IPv6 addresses (e.g. ``::1`` vs ``0:0:0:0:0:0:0:1``)
    are not folded together, so such a pair could still read as two outage
    domains. None of these shapes occur in any ``base_url`` this codebase
    produces today (every value traces to a fixed set of hardcoded,
    already-canonical HTTPS hostnames -- see ``_outage_domain``'s
    docstring), so this is intentionally not chased further here; a future
    provider whose entitled address genuinely takes one of these forms
    should extend this function with evidence of the specific case, not
    prophylactically.
    """
    text = base_url.strip()
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text.casefold()
    if not parsed.scheme or not parsed.hostname:
        return text.casefold()
    try:
        port = parsed.port
    except ValueError:
        return text.casefold()
    scheme = parsed.scheme.casefold()
    host = parsed.hostname.casefold()
    # urlsplit().hostname strips IPv6 literal brackets (``[::1]`` -> ``::1``).
    # Re-adding them whenever the host itself contains a colon -- before ever
    # conditionally appending a port -- is required for two reasons: without
    # it, an explicit-port IPv6 URL (``[::1]:8443``) and a bracketless,
    # colon-bearing literal address that merely *looks* like host:port when
    # flattened (``[::1:8443]``, port None) collapse to the identical
    # ``::1:8443`` string despite being different addresses; and the
    # reassembled ``netloc`` must stay valid host:port syntax regardless.
    bracketed_host = f"[{host}]" if ":" in host else host
    netloc = (
        bracketed_host
        if port is None or port == _DEFAULT_PORTS.get(scheme)
        else f"{bracketed_host}:{port}"
    )
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def _admission_priority_key(
    row: Mapping[str, Any], *, zdr_endpoints: frozenset[str]
) -> tuple[int, int, str, str]:
    """Return the deterministic ``(cost tier, ZDR tier, provider, model)`` sort key.

    The single source of truth for admission priority: ``build_zdr_
    prioritized_catalog`` sorts ``eligible_rows`` with this key, and
    :func:`_fair_admission_order` re-derives just its first two components
    (the tier, excluding the ``(provider, model)`` tie-break) to find tier
    boundaries in that same sorted sequence -- sharing one function instead
    of two independently written key expressions means the two can never
    silently drift out of sync with each other.
    """
    return (
        _COST_EVIDENCE_RANK[_cost_evidence(row)],
        0
        if is_zdr_model(
            str(row["provider"]), model=str(row["model"]), zdr_endpoints=zdr_endpoints
        )
        else 1,
        str(row["provider"]),
        str(row["model"]),
    )


def _fair_admission_order(
    rows: list[Mapping[str, Any]], *, zdr_endpoints: frozenset[str]
) -> list[Mapping[str, Any]]:
    """Reorder rows so one outage domain's cap fills fairly across accounts.

    ``rows`` must already be sorted by :func:`_admission_priority_key` (see
    ``build_zdr_prioritized_catalog``'s own sort, which uses the same key).
    Grouping the admission cap by outage domain (:func:`_outage_domain`)
    fixed one starvation bug -- two same-endpoint credentials sharing one
    budget instead of each getting their own -- but introduced a second,
    narrower one: the greedy admission loop consumes rows in sorted order,
    so whichever account's rows happen to sort first (``"nvidia_nim"``
    before ``"nvidia_nim_sub"``, alphabetically, in every real fixture in
    this file) could exhaust the *entire* shared cap before the domain's
    other account was considered at all -- not "prevented from taking more
    than its share", but shut out completely, even with rows of its own
    available and cap budget nominally unused by it.

    Fairness is reordered strictly *within* one admission-priority tier
    (the ``(cost tier, ZDR tier)`` pair -- the first two components of
    :func:`_admission_priority_key`), never across tiers: an earlier
    revision of this function grouped every row for one outage domain into
    a single block at that domain's first appearance in the whole input,
    regardless of tier, which could drag a lower-priority route (e.g. paid,
    non-ZDR) from one domain ahead of a higher-priority route (e.g. free,
    ZDR) belonging to a *different* domain that happened to appear later in
    the original order -- a real correctness regression for a catalog whose
    entire purpose is admitting free/ZDR routes preferentially. Splitting
    ``rows`` into contiguous same-tier runs first (safe because the input
    is already tier-sorted, so equal-tier rows are already contiguous) and
    reordering fairness independently within each run, then concatenating
    the runs back in their original order, makes tier priority strictly
    non-negotiable: no row from a worse tier can ever end up ahead of a row
    from a better tier, regardless of domain/account composition.

    Within one tier, a domain contributed to by only one account is
    returned completely untouched, in its original relative position --
    this function changes nothing for the common case (every provider
    except the shared ``nvidia_nim``/``nvidia_nim_sub`` pair, as of this
    writing). Within a domain shared by more than one account, rows are
    taken in round-robin turns across those accounts -- one row from
    account A's own queue (which keeps A's rows in their original relative
    order), then one from B's, cycling only over accounts that still have
    an unconsumed row -- instead of admission naturally exhausting
    whichever account's rows sort first. This guarantees every contending
    account gets at least one turn before any account gets a second
    admission from that domain, so the domain's cap is filled
    proportionally across its accounts rather than by whichever one
    happens to rank first within the tier; an account that runs out of rows
    before the cap is reached simply stops participating in further
    rounds, letting the domain's remaining accounts absorb the leftover
    capacity. Crucially, a shared domain's own rows keep the exact global
    positions they already occupied among ``rows`` -- round-robin only
    decides which of the domain's own rows lands in which of its own
    positions, never how far ahead or behind an unrelated domain's row
    sits (see :func:`_fair_order_within_tier`'s docstring for the concrete
    bug an earlier revision had here: collapsing a shared domain into one
    contiguous block at its first appearance silently displaced an
    unrelated domain's row that had been priority-ranked between two of
    the shared domain's own occurrences).
    """
    ordered: list[Mapping[str, Any]] = []
    tier_start = 0
    total = len(rows)
    while tier_start < total:
        tier = _admission_priority_key(rows[tier_start], zdr_endpoints=zdr_endpoints)[:2]
        tier_end = tier_start + 1
        while (
            tier_end < total
            and _admission_priority_key(rows[tier_end], zdr_endpoints=zdr_endpoints)[:2]
            == tier
        ):
            tier_end += 1
        ordered.extend(_fair_order_within_tier(rows[tier_start:tier_end]))
        tier_start = tier_end
    return ordered


def _fair_order_within_tier(
    rows: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    """Round-robin one already-single-tier run of rows across shared-domain accounts.

    See :func:`_fair_admission_order`'s docstring for why fairness must stay
    scoped to one admission-priority tier at a time; this is that per-tier
    reordering step, factored out so it never has visibility into rows from
    a different tier to (mis)order against.

    This never collapses a domain's rows into one contiguous block. An
    earlier revision grouped every row for one domain at that domain's
    *first* appearance in ``rows``, which silently moved rows belonging to
    *other* domains whenever a shared domain's own rows were not already
    contiguous in the input: e.g. ``[A1, B1, A2]`` (domain A shared by two
    accounts, with an unrelated domain B's row ranked between A's two
    occurrences) became ``[A1, A2, B1]`` under that revision -- B1, an
    independent domain's row that had outranked A2, was pushed behind
    *both* of A's rows, which could drop B1 entirely under a tight
    admission limit even though it was priority-ranked ahead of A2.
    Instead, each domain keeps exactly the global positions its own rows
    already occupy (recorded in ``domain_positions`` below); round-robining
    a shared domain's accounts only decides which of *that domain's own*
    rows fills each of its own positions, so a shared domain's Nth admitted
    row can only displace what its own Nth-occurrence priority position
    would have displaced, never a different domain's row.
    """
    domain_positions: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        domain_positions.setdefault(_outage_domain(row), []).append(index)

    ordered: list[Mapping[str, Any]] = list(rows)
    for positions in domain_positions.values():
        bucket = [rows[index] for index in positions]
        account_order: list[str] = []
        queues: dict[str, deque[Mapping[str, Any]]] = {}
        for row in bucket:
            account = provider_account(str(row["provider"]))
            if account not in queues:
                account_order.append(account)
                queues[account] = deque()
            queues[account].append(row)
        if len(account_order) <= 1:
            continue
        reordered: list[Mapping[str, Any]] = []
        while any(queues[account] for account in account_order):
            for account in account_order:
                queue = queues[account]
                if queue:
                    reordered.append(queue.popleft())
        for index, row in zip(positions, reordered):
            ordered[index] = row
    return ordered


def _normalize_agent_id(candidate: str, provider_name: str) -> str:
    """Return a two-or-more-word snake_case agent identifier."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", candidate).strip("_").lower()
    parts = [part for part in slug.split("_") if part]
    if len(parts) == 1:
        parts.insert(0, provider_name)
    return "_".join(parts)


def _route_key(provider_name: str, model: str) -> str:
    """Return the provider/model key used by the ZDR feed."""
    return route_key(provider_name, model)


def _is_valid_is_free(value: object) -> bool:
    """Return whether a row carries an explicit scalar free marker."""
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    return False


def _validated_price(value: object, *, route: str, field: str) -> float:
    """Return a finite nonnegative published price or reject it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"model {route} lacks numeric {field} evidence")
    price = float(value)
    if not math.isfinite(price) or price < 0:
        raise PolicyError(f"model {route} has invalid {field} evidence")
    return price


def _normalize_cost_evidence(
    *,
    route: str,
    is_free: bool,
    prompt_price: object,
    completion_price: object,
    currency_code: object,
) -> tuple[str, float | None, float | None, str | None]:
    """Classify complete free, priced, or wholly unavailable price evidence.

    A provider that publishes neither price component is retained for audit but
    is not eligible for review routing. A partial vector is ambiguous and
    rejected. Free markers remain authoritative only when any accompanying
    published vector is complete, valid, and zero-priced.
    """
    if prompt_price is None and completion_price is None:
        return (COST_UNKNOWN, None, None, None)

    normalized_prompt = _validated_price(
        prompt_price, route=route, field="prompt_price_per_1k"
    )
    normalized_completion = _validated_price(
        completion_price, route=route, field="completion_price_per_1k"
    )
    if not isinstance(currency_code, str) or not currency_code.strip():
        raise PolicyError(f"model {route} lacks currency_code evidence")
    if is_free and (normalized_prompt != 0 or normalized_completion != 0):
        raise PolicyError(f"model {route} conflicts with its free price marker")
    return (
        COST_FREE if is_free else COST_PRICED,
        normalized_prompt,
        normalized_completion,
        currency_code.strip().upper(),
    )


def parse_discovery_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate and normalize a contextual-orchestrator discovery report."""
    rows = report.get("models")
    if not isinstance(rows, list):
        raise PolicyError("discovery report must contain a 'models' list")

    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise PolicyError("each discovery model row must be an object")
        provider = row.get("provider")
        model = row.get("model")
        if not provider or not isinstance(provider, str):
            raise PolicyError("discovery model row is missing 'provider'")
        if not model or not isinstance(model, str):
            raise PolicyError("discovery model row is missing 'model'")
        if provider not in PROVIDER_CREDENTIAL_NAMES:
            raise PolicyError(
                f"provider {provider!r} is not registered in the ZDR policy table"
            )
        if not _is_valid_is_free(row.get("is_free")):
            raise PolicyError(
                f"model {provider}/{model} lacks an explicit is_free marker"
            )

        is_free = is_free_route(row.get("is_free"))
        route = f"{provider}/{model}"
        cost_evidence, prompt_price, completion_price, currency_code = (
            _normalize_cost_evidence(
                route=route,
                is_free=is_free,
                prompt_price=row.get("prompt_price_per_1k"),
                completion_price=row.get("completion_price_per_1k"),
                currency_code=row.get("currency_code"),
            )
        )
        candidate_id = row.get("agent_id") or f"{provider}_{model}"
        normalized.append(
            {
                "provider": provider,
                "model": model,
                "agent_id": str(candidate_id),
                "is_free": is_free,
                "cost_evidence": cost_evidence,
                "prompt_price_per_1k": prompt_price,
                "completion_price_per_1k": completion_price,
                "currency_code": currency_code,
                "base_url": row.get("base_url") or PROVIDER_BASE_URLS[provider],
                "credential_key": row.get("credential_key")
                or PROVIDER_CREDENTIAL_NAMES[provider],
                "auth_scheme": row.get("auth_scheme")
                or PROVIDER_AUTH_SCHEMES[provider],
            }
        )
    return normalized


def _cost_evidence(row: Mapping[str, Any]) -> str:
    """Return a validated cost-evidence tier from a normalized row."""
    evidence = row.get("cost_evidence")
    if evidence in _COST_EVIDENCE_RANK:
        return str(evidence)
    # Backward compatibility for callers that build normalized-like rows by
    # hand rather than using parse_discovery_report().
    return COST_FREE if row.get("is_free") is True else COST_UNKNOWN


def build_zdr_prioritized_catalog(
    rows: Iterable[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_CATALOG_LIMIT,
    account_cap: int = DEFAULT_ACCOUNT_CAP,
    zdr_endpoints: frozenset[str] = frozenset(),
    require_zdr: bool = False,
    pool: str = "free",
    guarantee_domain_coverage: bool = False,
) -> dict[str, Any]:
    """Select a free-first, ZDR-aware, outage-domain-diverse catalog.

    The returned report carries two distinct diversity/admission signals,
    deliberately kept separate (see :func:`_outage_domain`'s docstring for
    the full rationale):

    - ``free_account_diversity`` counts the distinct credential accounts
      (:func:`provider_account`) among *all* discovered free routes. Vendor
      identity is not model equivalence -- ``nvidia_nim`` and
      ``nvidia_nim_sub`` are independent here, since either may be entitled
      to a different model catalog; only an explicit contextual-orchestrator
      ``model_group`` may share routing evidence across routes.
    - ``free_outage_domain_diversity`` counts the distinct shared-
      infrastructure outage domains (:func:`_outage_domain`, keyed on each
      row's own ``base_url``) among the same routes. ``nvidia_nim`` and
      ``nvidia_nim_sub`` collapse to *one* domain here, since both resolve to
      the identical upstream endpoint -- a caller deciding whether it is
      safe to rely on a strict, fail-closed ``orchestrator/free`` pool
      without an ``orchestrator/auto`` paid-route safety net (the actual
      question ADR-0003 raised) should require at least two here, not on
      ``free_account_diversity``: one shared endpoint's outage can empty the
      free catalog even when two independent credentials both point at it.

    Both are computed independent of ``pool`` or the per-domain admission
    cap below. The admission cap itself (``account_cap`` -- the name
    predates this fix and is kept for CLI/environment stability, but its
    grouping is by outage domain, matching the cap's original purpose:
    preventing one physical endpoint from absorbing the bounded catalog, the
    confirmed root cause of a real 2026-08-30 ``orchestrator/free``
    exhaustion incident recorded in ``docs/product-technical-gap-
    baseline.md``) admits at most ``account_cap`` rows per outage domain,
    not per credential -- two same-endpoint credentials share one cap
    budget, they do not each get their own.

    This counts routes discovery reports as free, not routes runtime
    preflight has confirmed are actually serving requests: a
    ``free_outage_domain_diversity`` of two or more is evidence that one
    endpoint's outage cannot immediately empty the free catalog, not proof
    that either domain is presently reachable. A caller needing readiness,
    not just discovery-time diversity, must combine this with the runtime
    preflight report the sidecar already produces.

    ``guarantee_domain_coverage`` (default ``False``, preserving every
    existing caller's behavior unchanged) fixes a narrower gap a uniform
    ``account_cap`` cannot: when ``limit`` is small relative to the number
    of competing outage domains -- the review sidecar's priced-fallback
    stage's own real shape, where ``limit`` and ``account_cap`` can both be
    4 -- a single scalar cap forces an uncomfortable choice between two
    failure modes. A cap left at ``account_cap`` lets one dominant domain
    exhaust ``limit`` before a second domain is ever considered (Devin
    Review: "fallback remains single-domain"). Shrinking the cap to
    ``limit // domain_count`` fixes that but wastes admittable capacity
    whenever ``limit`` does not divide evenly (Devin Review, same PR:
    "fallback quota wastes probe slots" -- concretely, ``limit=4`` across 3
    domains admits only 3 routes under a uniform floor of 1, even though a
    4th eligible row exists in one of those domains). When set, admission
    runs in two passes instead of one: the first pass admits at most one
    row per outage domain (bounded by ``account_cap`` and ``limit``, in the
    same priority order the single-pass loop already uses), guaranteeing
    every domain with an eligible row is represented before any domain
    claims a second seat; the second pass then fills any remaining
    ``limit`` budget from the rows the first pass did not pick, still
    respecting each domain's ``account_cap`` ceiling (inclusive of what the
    first pass already gave it), from whichever domain's next-highest-
    priority row comes first -- so the full budget is used whenever enough
    eligible rows exist anywhere, not artificially left idle. The picked
    order places every first-pass (diversity) row ahead of every
    second-pass (fill) row: for a fallback pool whose entire purpose is
    outage-domain resilience, trying one candidate from each domain before
    a second candidate from an already-represented domain is the more
    useful preflight order, not merely a side effect of the two-pass
    implementation.

    Both passes run strictly *within* one admission-priority tier at a
    time, in tier order (Devin Review: "domain coverage defeats ZDR
    priority") -- the same tier-boundary discipline :func:`_fair_admission_order`
    already enforces for its own reordering, applied here too, because
    ``ordered_rows`` mixes every tier when this flag is used at a catalog's
    primary (not fallback-only) stage. Without it, a worse-tier row could
    win a first-pass "guaranteed representation" seat for its domain ahead
    of a better-tier row from an already-represented domain -- e.g. two
    free/ZDR rows in domain A and one free/non-ZDR row in domain B with
    ``limit=2`` would wrongly admit one row from each domain instead of
    both of A's free/ZDR rows. Processing tier-by-tier (finishing a tier's
    own first *and* second pass before ever looking at the next, worse
    tier) makes tier priority non-negotiable here exactly as it already is
    in :func:`_fair_admission_order`, while ``covered_domains`` and
    ``per_domain`` still accumulate across tiers: a domain already given a
    seat in a better tier does not claim a second guaranteed seat in a
    worse one, and ``account_cap`` bounds a domain's total admissions
    across the whole catalog, not per tier.
    """
    if pool not in {"free", "auto"}:
        raise PolicyError(f"unsupported review pool {pool!r}")

    all_rows = list(rows)
    all_free_rows = [row for row in all_rows if _cost_evidence(row) == COST_FREE]
    all_priced_rows = [row for row in all_rows if _cost_evidence(row) == COST_PRICED]
    all_unknown_rows = [row for row in all_rows if _cost_evidence(row) == COST_UNKNOWN]
    candidate_rows = (
        all_free_rows if pool == "free" else [*all_free_rows, *all_priced_rows]
    )
    eligible_rows = [
        row
        for row in candidate_rows
        if not require_zdr
        or is_zdr_model(
            str(row["provider"]),
            model=str(row["model"]),
            zdr_endpoints=zdr_endpoints,
        )
    ]
    eligible_rows.sort(
        key=lambda row: _admission_priority_key(row, zdr_endpoints=zdr_endpoints)
    )

    per_domain: Counter[str] = Counter()
    picked: list[Mapping[str, Any]] = []
    ordered_rows = _fair_admission_order(eligible_rows, zdr_endpoints=zdr_endpoints)
    if guarantee_domain_coverage:
        covered_domains: set[str] = set()
        tier_start = 0
        total = len(ordered_rows)
        while tier_start < total and len(picked) < limit:
            tier = _admission_priority_key(
                ordered_rows[tier_start], zdr_endpoints=zdr_endpoints
            )[:2]
            tier_end = tier_start + 1
            while (
                tier_end < total
                and _admission_priority_key(
                    ordered_rows[tier_end], zdr_endpoints=zdr_endpoints
                )[:2]
                == tier
            ):
                tier_end += 1
            tier_rows = ordered_rows[tier_start:tier_end]
            tier_start = tier_end

            first_pass_ids: set[int] = set()
            for row in tier_rows:
                if len(picked) >= limit:
                    break
                domain = _outage_domain(row)
                if domain in covered_domains or per_domain[domain] >= account_cap:
                    continue
                covered_domains.add(domain)
                per_domain[domain] += 1
                picked.append(row)
                first_pass_ids.add(id(row))
            for row in tier_rows:
                if len(picked) >= limit:
                    break
                if id(row) in first_pass_ids:
                    continue
                domain = _outage_domain(row)
                if per_domain[domain] >= account_cap:
                    continue
                per_domain[domain] += 1
                picked.append(row)
    else:
        for row in ordered_rows:
            domain = _outage_domain(row)
            if per_domain[domain] >= account_cap:
                continue
            per_domain[domain] += 1
            picked.append(row)
            if len(picked) >= limit:
                break

    if not picked:
        route_kind = "attested ZDR" if require_zdr else pool
        raise PolicyError(
            f"no {route_kind} model route is available with the ZDR policy; "
            f"orchestrator/{pool} would fail closed"
        )

    catalog_rows: list[dict[str, Any]] = []
    zdr_count = 0
    for rank, row in enumerate(picked):
        provider = str(row["provider"])
        model = str(row["model"])
        evidence = _cost_evidence(row)
        zdr = is_zdr_model(
            provider, model=model, zdr_endpoints=zdr_endpoints
        )
        if zdr:
            zdr_count += 1
        catalog_rows.append(
            {
                "id": _normalize_agent_id(str(row["agent_id"]), provider),
                "model": model,
                "base_url": row["base_url"],
                "api_key_env": "",
                "credential_key": row["credential_key"],
                "tags": [
                    "review",
                    f"cost:{evidence}",
                    "zdr" if zdr else "non-zdr",
                ],
                "priority": -rank,
                "disabled": False,
                "provider_name": provider,
                "provider_exclusions": [],
                "local_credential_key": "",
                "auth_scheme": row["auth_scheme"],
                "group_name": "",
                "reasoning_effort_supported": True,
                "endpoint_equivalence": None,
            }
        )

    free_account_diversity = len(
        {provider_account(str(row["provider"])) for row in all_free_rows}
    )
    free_outage_domain_diversity = len(
        {_outage_domain(row) for row in all_free_rows}
    )

    selected_evidence = [_cost_evidence(row) for row in picked]
    return {
        "agents": catalog_rows,
        "report": {
            "pool": f"orchestrator/{pool}",
            "total_routes": len(all_rows),
            "total_free_routes": len(all_free_rows),
            "total_priced_routes": len(all_priced_rows),
            "total_unknown_routes": len(all_unknown_rows),
            "free_account_diversity": free_account_diversity,
            "free_outage_domain_diversity": free_outage_domain_diversity,
            "zdr_required": require_zdr,
            "selected_count": len(catalog_rows),
            "free_selected_count": selected_evidence.count(COST_FREE),
            "priced_selected_count": selected_evidence.count(COST_PRICED),
            "unknown_selected_count": selected_evidence.count(COST_UNKNOWN),
            "zdr_selected_count": zdr_count,
            "zdr_sources": sorted(
                {
                    provider_zdr_scope(str(row["provider"])).source
                    for row in picked
                    if is_zdr_model(
                        str(row["provider"]),
                        model=str(row["model"]),
                        zdr_endpoints=zdr_endpoints,
                    )
                }
            ),
            "zdr_endpoints_feed_used": bool(zdr_endpoints),
            "selected": [
                {
                    "provider": row["provider"],
                    "model": row["model"],
                    "agent_id": entry["id"],
                    "cost_evidence": _cost_evidence(row),
                    "zdr": is_zdr_model(
                        str(row["provider"]),
                        model=str(row["model"]),
                        zdr_endpoints=zdr_endpoints,
                    ),
                }
                for row, entry in zip(picked, catalog_rows)
            ],
        },
    }


def _load_zdr_endpoints(path: str | None) -> frozenset[str]:
    """Load exact provider/model keys from an OpenRouter ZDR feed file."""
    if not path:
        return frozenset()
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    keys: set[str] = set()
    for endpoint in payload.get("data", []):
        provider = endpoint.get("provider_name")
        model = endpoint.get("model_name")
        if provider and model:
            keys.add(_route_key(str(provider), str(model)))
            keys.add(_route_key("openrouter", str(model)))
    return frozenset(keys)


def build_catalog_from_paths(
    discovery_path: str,
    *,
    out_path: str,
    report_path: str,
    limit: int = DEFAULT_CATALOG_LIMIT,
    account_cap: int = DEFAULT_ACCOUNT_CAP,
    zdr_endpoints_path: str | None = None,
    require_zdr: bool = False,
    pool: str = "free",
) -> dict[str, Any]:
    """Build and persist an agents catalog and its audit report."""
    report = json.loads(Path(discovery_path).read_text(encoding="utf-8"))
    result = build_zdr_prioritized_catalog(
        parse_discovery_report(report),
        limit=limit,
        account_cap=account_cap,
        zdr_endpoints=_load_zdr_endpoints(zdr_endpoints_path),
        require_zdr=require_zdr,
        pool=pool,
    )
    Path(out_path).write_text(
        json.dumps({"agents": result["agents"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(report_path).write_text(
        json.dumps(result["report"], indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser for catalog generation."""
    parser = argparse.ArgumentParser(
        description="Build a governed contextual-orchestrator review catalog."
    )
    parser.add_argument(
        "--discovery-report", required=True, help="Path to the discovery JSON"
    )
    parser.add_argument("--out", required=True, help="Path to write agents JSON")
    parser.add_argument("--report", required=True, help="Path to write audit JSON")
    parser.add_argument("--limit", type=int, default=DEFAULT_CATALOG_LIMIT)
    parser.add_argument("--account-cap", type=int, default=DEFAULT_ACCOUNT_CAP)
    parser.add_argument("--zdr-endpoints", default=None)
    parser.add_argument("--require-zdr", action="store_true")
    parser.add_argument("--pool", choices=("free", "auto"), default="free")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the catalog CLI and return one on policy or input failure."""
    args = _build_parser().parse_args(argv)
    try:
        build_catalog_from_paths(
            args.discovery_report,
            out_path=args.out,
            report_path=args.report,
            limit=args.limit,
            account_cap=args.account_cap,
            zdr_endpoints_path=args.zdr_endpoints,
            require_zdr=args.require_zdr,
            pool=args.pool,
        )
    except (PolicyError, OSError, json.JSONDecodeError) as exc:
        print(f"contextual-orchestrator review policy: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
