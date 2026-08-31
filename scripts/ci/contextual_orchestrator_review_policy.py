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
from collections import Counter
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
    port, a different path -- is preserved verbatim, including the query and
    fragment components (routing evidence has no legitimate reason to carry
    either; preserving rather than dropping them means an unexpected one
    cannot silently vanish from the computed identity). Any userinfo
    component present is dropped rather than preserved: outage-domain
    identity is about the physical endpoint, not which credential reaches
    it, and this codebase's base URLs never carry userinfo (see
    ``configured_gateway_source`` in ``contextual-orchestrator``, which
    rejects one outright).

    A string this cannot parse into a scheme, host, and numeric port --
    including an empty string (which would otherwise normalize to a value
    indistinct from a real one-character path) and a non-numeric port
    substring (``urlsplit(...).port`` raises ``ValueError`` for one) --
    falls back to a simple lowercased, stripped copy of the whole string:
    grouping only needs equal inputs to compare equal, not a validated URL,
    and this function must never raise on evidence it merely groups.
    """
    text = base_url.strip()
    parsed = urlsplit(text)
    if not parsed.scheme or not parsed.hostname:
        return text.casefold()
    try:
        port = parsed.port
    except ValueError:
        return text.casefold()
    scheme = parsed.scheme.casefold()
    host = parsed.hostname.casefold()
    netloc = host if port is None or port == _DEFAULT_PORTS.get(scheme) else f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, parsed.fragment))


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
        key=lambda row: (
            _COST_EVIDENCE_RANK[_cost_evidence(row)],
            0
            if is_zdr_model(
                str(row["provider"]),
                model=str(row["model"]),
                zdr_endpoints=zdr_endpoints,
            )
            else 1,
            str(row["provider"]),
            str(row["model"]),
        )
    )

    per_domain: Counter[str] = Counter()
    picked: list[Mapping[str, Any]] = []
    for row in eligible_rows:
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
