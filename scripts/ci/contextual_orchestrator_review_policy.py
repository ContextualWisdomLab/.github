"""Build governed contextual-orchestrator review catalogs from discovery evidence.

``orchestrator/free`` remains strictly zero-priced and admits only provider
accounts explicitly authorized for that pool. ``orchestrator/auto`` may retain
other globally discovered providers, including OpenAI, when their independent
policy permits them. Models without a complete price vector remain visible in
audit counts but are never admitted to CI review. Partial, malformed, or
contradictory price vectors fail closed.

This module is an admission boundary, not a router. It therefore must not invent
candidate-count caps, per-provider quotas, price/ZDR/provider ordering, hand-set
priorities, or fallback preferences. Every row satisfying the explicit pool,
price, credential-source, and optional ZDR predicates remains admitted with
neutral priority. Downstream model choice requires its own evidence-backed
routing contract.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from scripts.ci.zdr_policy import (
    PROVIDER_AUTH_SCHEMES,
    PROVIDER_BASE_URLS,
    PROVIDER_CREDENTIAL_NAMES,
    is_free_route,
    is_zdr_model,
    provider_zdr_scope,
    route_key,
)

# Compatibility-only values retained while callers migrate away from the old
# command surface. They are deliberately ignored by admission and therefore do
# not affect candidate membership, ordering, or priority.
DEFAULT_CATALOG_LIMIT = 12
DEFAULT_ACCOUNT_CAP = 4

FREE_POOL_CREDENTIAL_NAMES = frozenset(
    {
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
    }
)
"""Credential sources authorized to contribute to ``orchestrator/free``.

``OPENAI_API_KEY`` is intentionally absent. It may still be present, registered,
and globally discovered; only candidate admission to the free pool is denied.
"""

COST_FREE = "free"
COST_PRICED = "priced"
COST_UNKNOWN = "unknown"
_COST_EVIDENCE_VALUES = frozenset({COST_FREE, COST_PRICED, COST_UNKNOWN})

_AGENT_ID_RE = re.compile(r"^[a-z][a-z0-9]*_[a-z0-9]+(?:_[a-z0-9]+)*$")


class PolicyError(ValueError):
    """Raised when discovery evidence cannot produce a governed catalog."""


def provider_account(provider_name: str) -> str:
    """Return the independently credentialed provider account identity."""
    return provider_name


def _normalize_agent_id(candidate: str, provider_name: str) -> str:
    """Return a two-or-more-word snake_case agent identifier."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", candidate).strip("_").lower()
    parts = [part for part in slug.split("_") if part]
    if len(parts) == 1:
        parts.insert(0, provider_name)
    normalized = "_".join(parts)
    if not _AGENT_ID_RE.fullmatch(normalized):
        raise PolicyError(f"model agent id {candidate!r} cannot be normalized safely")
    return normalized


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

        expected_credential_key = PROVIDER_CREDENTIAL_NAMES[provider]
        supplied_credential_key = row.get("credential_key")
        credential_key = (
            expected_credential_key
            if supplied_credential_key is None
            else supplied_credential_key
        )
        if credential_key != expected_credential_key:
            raise PolicyError(
                f"model {provider}/{model} credential source does not match provider evidence"
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
                "credential_key": credential_key,
                "auth_scheme": row.get("auth_scheme")
                or PROVIDER_AUTH_SCHEMES[provider],
            }
        )
    return normalized


def _cost_evidence(row: Mapping[str, Any]) -> str:
    """Return a validated cost-evidence tier from a normalized row."""
    evidence = row.get("cost_evidence")
    if evidence in _COST_EVIDENCE_VALUES:
        return str(evidence)
    # Backward compatibility for callers that build normalized-like rows by
    # hand rather than using parse_discovery_report().
    return COST_FREE if row.get("is_free") is True else COST_UNKNOWN


def _free_pool_source_admitted(row: Mapping[str, Any]) -> bool:
    """Return whether a normalized row has an authorized free-pool source."""
    credential_key = row.get("credential_key")
    return (
        isinstance(credential_key, str)
        and credential_key in FREE_POOL_CREDENTIAL_NAMES
    )


def build_zdr_prioritized_catalog(
    rows: Iterable[Mapping[str, Any]],
    *,
    limit: object = DEFAULT_CATALOG_LIMIT,
    account_cap: object = DEFAULT_ACCOUNT_CAP,
    zdr_endpoints: frozenset[str] = frozenset(),
    require_zdr: bool = False,
    pool: str = "free",
) -> dict[str, Any]:
    """Compatibility-named admission API; it performs no prioritization.

    The historical function name is retained only so existing callers can roll
    forward without a flag-day. ``limit`` and ``account_cap`` are likewise
    compatibility-only: they are intentionally non-authoritative and are not
    inspected, validated, serialized, or allowed to remove, rank, or prioritize
    a candidate. The admission set is fully determined by explicit cost
    evidence, ``orchestrator/free`` credential-source authorization, and the
    caller's optional ZDR requirement.

    Input order is preserved only as discovery provenance. Every emitted agent
    has neutral priority, so this module does not convert that serialization
    order into routing authority.
    """
    if pool not in {"free", "auto"}:
        raise PolicyError(f"unsupported review pool {pool!r}")

    all_rows = list(rows)
    all_free_rows = [row for row in all_rows if _cost_evidence(row) == COST_FREE]
    free_pool_rows = [row for row in all_free_rows if _free_pool_source_admitted(row)]
    all_priced_rows = [row for row in all_rows if _cost_evidence(row) == COST_PRICED]
    all_unknown_rows = [row for row in all_rows if _cost_evidence(row) == COST_UNKNOWN]
    candidate_rows = (
        free_pool_rows
        if pool == "free"
        else [
            row
            for row in all_rows
            if _cost_evidence(row) in {COST_FREE, COST_PRICED}
        ]
    )
    picked = [
        row
        for row in candidate_rows
        if not require_zdr
        or is_zdr_model(
            str(row["provider"]),
            model=str(row["model"]),
            zdr_endpoints=zdr_endpoints,
        )
    ]

    if not picked:
        route_kind = "attested ZDR" if require_zdr else pool
        raise PolicyError(
            f"no {route_kind} model route is available with the ZDR policy; "
            f"orchestrator/{pool} would fail closed"
        )

    catalog_rows: list[dict[str, Any]] = []
    normalized_agent_ids: set[str] = set()
    zdr_count = 0
    for row in picked:
        provider = str(row["provider"])
        model = str(row["model"])
        evidence = _cost_evidence(row)
        agent_id = _normalize_agent_id(str(row["agent_id"]), provider)
        if agent_id in normalized_agent_ids:
            raise PolicyError(f"agent id collision after normalization: {agent_id!r}")
        normalized_agent_ids.add(agent_id)
        zdr = is_zdr_model(provider, model=model, zdr_endpoints=zdr_endpoints)
        if zdr:
            zdr_count += 1
        catalog_rows.append(
            {
                "id": agent_id,
                "model": model,
                "base_url": row["base_url"],
                "api_key_env": "",
                "credential_key": row["credential_key"],
                "tags": [
                    "review",
                    f"cost:{evidence}",
                    "zdr" if zdr else "non-zdr",
                ],
                "priority": 0,
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
    free_pool_account_diversity = len(
        {provider_account(str(row["provider"])) for row in free_pool_rows}
    )
    selected_evidence = [_cost_evidence(row) for row in picked]
    return {
        "agents": catalog_rows,
        "report": {
            "pool": f"orchestrator/{pool}",
            "total_routes": len(all_rows),
            "total_free_routes": len(all_free_rows),
            "free_account_diversity": free_account_diversity,
            "free_pool_admitted_routes": len(free_pool_rows),
            "free_pool_excluded_source_count": len(all_free_rows) - len(free_pool_rows),
            "free_pool_account_diversity": free_pool_account_diversity,
            "total_priced_routes": len(all_priced_rows),
            "total_unknown_routes": len(all_unknown_rows),
            "zdr_required": require_zdr,
            "selected_count": len(catalog_rows),
            "free_selected_count": selected_evidence.count(COST_FREE),
            "priced_selected_count": selected_evidence.count(COST_PRICED),
            "unknown_selected_count": selected_evidence.count(COST_UNKNOWN),
            "zdr_selected_count": zdr_count,
            "legacy_limit_ignored": True,
            "legacy_account_cap_ignored": True,
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
    limit: object = DEFAULT_CATALOG_LIMIT,
    account_cap: object = DEFAULT_ACCOUNT_CAP,
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


def _warn_explicit_legacy_options(argv: list[str]) -> None:
    """Warn when obsolete cardinality options remain in operator configuration."""
    for option in ("--limit", "--account-cap"):
        if any(argument == option or argument.startswith(f"{option}=") for argument in argv):
            print(
                f"contextual-orchestrator review policy: {option} is deprecated and ignored",
                file=sys.stderr,
            )


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
    parser.add_argument(
        "--limit",
        default=DEFAULT_CATALOG_LIMIT,
        help="Deprecated compatibility input; does not affect admission.",
    )
    parser.add_argument(
        "--account-cap",
        default=DEFAULT_ACCOUNT_CAP,
        help="Deprecated compatibility input; does not affect admission.",
    )
    parser.add_argument("--zdr-endpoints", default=None)
    parser.add_argument("--require-zdr", action="store_true")
    parser.add_argument("--pool", choices=("free", "auto"), default="free")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the catalog CLI and return one on policy or input failure."""
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    args = _build_parser().parse_args(effective_argv)
    _warn_explicit_legacy_options(effective_argv)
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
