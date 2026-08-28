"""Turn an orchestrator discovery report into a ZDR-prioritized ``orchestrator/free`` catalog.

The contextual-orchestrator server exposes the fail-closed zero-cost pool under
the virtual model id ``orchestrator/free``; it only resolves when at least one
enabled agent is an explicitly zero-priced (``cost:free``) model
(``contextual_orchestrator/orchestrator.py`` ``_is_free_agent``). This module,

1. reads the same ``discover-models`` report the orchestrator prints,
2. keeps only free (zero-cost), known-provider chat routes,
3. treats OpenRouter as a ZDR evidence source rather than a routed upstream,
   orders the remaining routes ZDR-compliant first, then non-ZDR free, with a
   provider-family cap so a single outage domain cannot monopolize the pool,
4. writes an ``agents`` JSON catalog in the orchestrator's own
   ``ModelAgent.to_config()`` schema so the vendored sidecar can
   ``load_agents()`` it unchanged.

Everything is stdlib-only and offline-testable; the live OpenRouter ZDR feed is
an optional input file so CI either attests real ZDR endpoints or falls back to
the static ``scripts/ci/zdr_policy.py`` table (never fabricated).
"""

from __future__ import annotations

import argparse
import json
import sys
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

from scripts.ci.zdr_policy import (
    OPENROUTER_ZDR_ENDPOINTS_SOURCE,
    PROVIDER_AUTH_SCHEMES,
    PROVIDER_BASE_URLS,
    PROVIDER_CREDENTIAL_NAMES,
    is_free_route,
    is_zdr_model,
    provider_zdr_scope,
    route_key,
)

# NVIDIA primary and secondary keys share one outage domain for provider-family
# diversity, mirroring contextual_orchestrator ``_provider_family``.
PROVIDER_FAMILIES: Mapping[str, str] = {
    "nvidia_nim": "nvidia_nim",
    "nvidia_nim_sub": "nvidia_nim",
}

# OpenRouter's public catalog informs ZDR eligibility for other providers; it
# is not itself an upstream in this review sidecar's model group.
EVIDENCE_ONLY_PROVIDERS = frozenset({"openrouter"})

DEFAULT_CATALOG_LIMIT = 12
DEFAULT_FAMILY_CAP = 4

_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9]*_[a-z0-9]+(?:_[a-z0-9]+)*$")


def provider_family(provider_name: str) -> str:
    """Return the outage-domain family for a provider (itself when ungrouped)."""
    return PROVIDER_FAMILIES.get(provider_name, provider_name)


def _normalize_agent_id(candidate: str, provider_name: str) -> str:
    """Return a valid two-or-more-word snake_case agent id.

    The orchestrator requires agent ids to match the org naming convention
    (``[tool.contextual_orchestrator] object_name_pattern =
    two_or_more_words_snake_case``). Discovery emits ids like
    ``openrouter_deepseek_deepseek_r1_free``; this normalizes any provider/model
    string that does not already comply.

    Args:
        candidate: Candidate agent id from the discovery report.
        provider_name: Provider identifier used as the first segment fallback.

    Returns:
        A naming-compliant snake_case id.
    """
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", candidate).strip("_").lower()
    parts = [part for part in slug.split("_") if part]
    if len(parts) == 1:
        parts.insert(0, provider_name)
    return "_".join(parts)


def _route_key(provider_name: str, model: str) -> str:
    """Return the ``provider/model`` key used by the ZDR endpoints feed."""
    return route_key(provider_name, model)


def _is_valid_is_free(value: object) -> bool:
    """Return whether a report row carries an explicit free marker."""
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    return False


class PolicyError(ValueError):
    """Raised when a discovery report cannot produce a usable catalog."""


def parse_discovery_report(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Validate and extract the model rows from a ``discover-models`` report.

    Args:
        report: Parsed JSON report with a top-level ``models`` list; each row
            must carry ``provider``, ``model``, and ``is_free``.

    Returns:
        A list of normalized row dicts with ``provider``, ``model``, ``agent_id``
        (fallback to provider_model), and an explicit boolean ``is_free``.

    Raises:
        PolicyError: If the report has no ``models`` list, or any row lacks a
            provider/model, or names a provider outside the ZDR policy table so
            routing cannot silently bypass the policy.
    """
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
            raise PolicyError(f"provider {provider!r} is not registered in the ZDR policy table")
        candidate_id = row.get("agent_id") or f"{provider}_{model}"
        if not _is_valid_is_free(row.get("is_free")):
            raise PolicyError(f"model {provider}/{model} lacks an explicit is_free marker")
        normalized.append(
            {
                "provider": provider,
                "model": model,
                "agent_id": str(candidate_id),
                "is_free": is_free_route(row.get("is_free")),
                "base_url": row.get("base_url") or PROVIDER_BASE_URLS[provider],
                "credential_key": row.get("credential_key") or PROVIDER_CREDENTIAL_NAMES[provider],
                "auth_scheme": row.get("auth_scheme") or PROVIDER_AUTH_SCHEMES[provider],
            }
        )
    return normalized


def build_zdr_prioritized_catalog(
    rows: Iterable[Mapping[str, Any]],
    *,
    limit: int = DEFAULT_CATALOG_LIMIT,
    family_cap: int = DEFAULT_FAMILY_CAP,
    zdr_endpoints: frozenset[str] = frozenset(),
    require_zdr: bool = False,
) -> dict[str, Any]:
    """Select and rank free routes into a ZDR-first, family-diverse catalog.

    Ranking is deterministic and evidence-based, never heuristic cost guesses:
    free (zero-cost, attested by discovery price metadata) routes always outrank
    any priced route; among free routes ZDR-compliant routes outrank the rest;
    within a tier the provider/model order is stable. A provider-family cap
    prevents the primary and secondary NVIDIA keys from absorbing the whole
    pool. Priced routes are excluded because the org's CI review path is pinned
    to the ``orchestrator/free`` pool.

    Args:
        rows: Normalized discovery rows (see ``parse_discovery_report``).
        limit: Maximum number of catalog agents (orchestrator default 12).
        family_cap: Maximum agents per provider outage-domain family.
        zdr_endpoints: ``provider/model`` route keys from the OpenRouter ZDR
            feed; authoritative for OpenRouter routes and for an exact or
            unambiguous model-identity match on another provider row.
        require_zdr: Admit only routes with attested ZDR evidence. Intended for
            private/internal target repositories; an empty ZDR pool fails closed.

    Returns:
        A dict with ``agents`` (orchestrator ``ModelAgent.to_config()`` rows,
        ZDR-first) and ``report`` (counts + evidence for audit).

    Raises:
        PolicyError: If no free, known-provider route remains (the catalog
            would fail closed at serve time anyway, but this makes the failure
            early and explainable).
    """
    catalog_rows: list[dict[str, Any]] = []
    per_family: Counter[str] = Counter()
    zdr_count = 0

    def family_is_open(family: str) -> bool:
        """Return whether a provider family still has catalog capacity."""
        return per_family[family] < family_cap

    discovered_free_rows = [row for row in rows if row["is_free"]]
    all_free_rows = [
        row
        for row in discovered_free_rows
        if row["provider"] not in EVIDENCE_ONLY_PROVIDERS
    ]
    free_rows = [
        row
        for row in all_free_rows
        if not require_zdr
        or is_zdr_model(
            row["provider"], model=row["model"], zdr_endpoints=zdr_endpoints
        )
    ]
    free_rows.sort(
        key=lambda row: (
            0
            if is_zdr_model(
                row["provider"], model=row["model"], zdr_endpoints=zdr_endpoints
            )
            else 1,
        )
    )
    picked: list[dict[str, Any]] = []
    for _order, row in enumerate(free_rows):
        family = provider_family(row["provider"])
        if not family_is_open(family):
            continue
        per_family[family] += 1
        picked.append(row)
        if len(picked) >= limit:
            break

    if not picked:
        route_kind = "attested ZDR free" if require_zdr else "free (zero-cost)"
        raise PolicyError(
            f"no {route_kind} model route is available with the ZDR policy; "
            "orchestrator/free would fail closed"
        )

    for rank, row in enumerate(picked):
        zdr = is_zdr_model(
            row["provider"], model=row["model"], zdr_endpoints=zdr_endpoints
        )
        if zdr:
            zdr_count += 1
        catalog_rows.append(
            {
                "id": _normalize_agent_id(row["agent_id"], row["provider"]),
                "model": row["model"],
                "base_url": row["base_url"],
                "api_key_env": "",
                "credential_key": row["credential_key"],
                "tags": ["review", "cost:free", "zdr" if zdr else "non-zdr"],
                "priority": -rank,
                "disabled": False,
                "provider_name": row["provider"],
                "provider_exclusions": [],
                "local_credential_key": "",
                "auth_scheme": row["auth_scheme"],
                "group_name": "",
                "reasoning_effort_supported": True,
                "endpoint_equivalence": None,
            }
        )

    return {
        "agents": catalog_rows,
        "report": {
            "pool": "orchestrator/free",
            "total_free_routes": len(all_free_rows),
            "evidence_only_free_routes": len(discovered_free_rows) - len(all_free_rows),
            "zdr_required": require_zdr,
            "selected_count": len(catalog_rows),
            "free_selected_count": len(picked),
            "zdr_selected_count": zdr_count,
            "zdr_sources": sorted(
                {
                    (
                        OPENROUTER_ZDR_ENDPOINTS_SOURCE
                        if zdr_endpoints
                        and (
                            provider_zdr_scope(row["provider"]).openrouter_endpoints_feed
                            or not provider_zdr_scope(row["provider"]).zero_data_retention
                        )
                        else provider_zdr_scope(row["provider"]).source
                    )
                    for row in picked
                    if is_zdr_model(
                        row["provider"], model=row["model"], zdr_endpoints=zdr_endpoints
                    )
                }
            ),
            "zdr_endpoints_feed_used": bool(zdr_endpoints),
            "selected": [
                {
                    "provider": row["provider"],
                    "model": row["model"],
                    "agent_id": entry["id"],
                    "zdr": is_zdr_model(row["provider"], model=row["model"], zdr_endpoints=zdr_endpoints),
                }
                for row, entry in zip(picked, catalog_rows)
            ],
        },
    }


def _load_zdr_endpoints(path: str | None) -> frozenset[str]:
    """Load ``provider/model`` ZDR route keys from the OpenRouter ZDR feed.

    Args:
        path: Path to the feed JSON (shape ``{\"data\": [{\"name\", \"model_name\",
            \"provider_name\", \"supports_implicit_caching\"}]}``); None yields no
            feed evidence.

    Returns:
        A frozen set of ``f\"{provider_name}/{model_name}\"`` keys.
    """
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
    family_cap: int = DEFAULT_FAMILY_CAP,
    zdr_endpoints_path: str | None = None,
    require_zdr: bool = False,
) -> dict[str, Any]:
    """Build and persist the ZDR-prioritized ``orchestrator/free`` catalog.

    Args:
        discovery_path: Path to the ``discover-models`` JSON report.
        out_path: Where to write the agents catalog JSON.
        report_path: Where to write the audit/evidence JSON report.
        limit: Maximum number of catalog agents.
        family_cap: Maximum agents per provider outage-domain family.
        zdr_endpoints_path: Optional OpenRouter ZDR feed JSON path.
        require_zdr: Admit only attested ZDR routes and fail closed otherwise.

    Returns:
        The return value of ``build_zdr_prioritized_catalog`` (both files were
        also written).
    """
    report = json.loads(Path(discovery_path).read_text(encoding="utf-8"))
    zdr_endpoints = _load_zdr_endpoints(zdr_endpoints_path)
    result = build_zdr_prioritized_catalog(
        parse_discovery_report(report),
        limit=limit,
        family_cap=family_cap,
        zdr_endpoints=zdr_endpoints,
        require_zdr=require_zdr,
    )
    Path(out_path).write_text(
        json.dumps({"agents": result["agents"]}, indent=2) + "\n", encoding="utf-8"
    )
    Path(report_path).write_text(json.dumps(result["report"], indent=2) + "\n", encoding="utf-8")
    return result


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser with the required catalog and report paths."""
    parser = argparse.ArgumentParser(
        description="Build a ZDR-prioritized orchestrator/free agents catalog from a discovery report."
    )
    parser.add_argument("--discovery-report", required=True, help="Path to the discover-models JSON report")
    parser.add_argument("--out", required=True, help="Path to write the agents catalog JSON")
    parser.add_argument("--report", required=True, help="Path to write the audit evidence JSON")
    parser.add_argument("--limit", type=int, default=DEFAULT_CATALOG_LIMIT)
    parser.add_argument("--family-cap", type=int, default=DEFAULT_FAMILY_CAP)
    parser.add_argument("--zdr-endpoints", default=None, help="Optional OpenRouter /api/v1/endpoints/zdr JSON path")
    parser.add_argument("--require-zdr", action="store_true", help="Fail closed unless every selected route has attested ZDR evidence")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns 1 on PolicyError/unusable catalog (fail closed).

    Args:
        argv: CLI arguments (defaults to ``sys.argv[1:]``).

    Returns:
        0 on success; 1 when the catalog cannot be built.
    """
    args = _build_parser().parse_args(argv)
    try:
        build_catalog_from_paths(
            args.discovery_report,
            out_path=args.out,
            report_path=args.report,
            limit=args.limit,
            family_cap=args.family_cap,
            zdr_endpoints_path=args.zdr_endpoints,
            require_zdr=args.require_zdr,
        )
    except (PolicyError, OSError, json.JSONDecodeError) as exc:
        print(f"contextual-orchestrator review policy: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
