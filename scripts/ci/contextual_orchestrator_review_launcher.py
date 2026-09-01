"""Serve the governed contextual-orchestrator review sidecar.

The launcher intentionally performs only evidence-based admission. It does not
rank provider routes, cap providers/accounts, infer model capability from model
names, or remove candidates after a synthetic generation probe. All five
provider credentials may be registered and globally discovered. The narrower
``orchestrator/free`` source boundary remains enforced by
``contextual_orchestrator_review_policy`` so OpenAI-derived models cannot enter
the free review pool.

Runtime provider failures are handled by contextual-orchestrator itself rather
than by a second CI-only router. This keeps Noema/OpenCode/Strix on the same
serving semantics as the organization gateway and removes the former fixed
preflight token budgets, escalation quotas, route caps, account caps, and
manufactured priorities.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Iterable


_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL = "discovery_diagnostics_complete"


def _log_discovery_errors(errors: Iterable[object]) -> None:
    """Print bounded secret-free provider discovery diagnostics."""
    for error in errors:
        print(
            f"provider_discovery_failed provider={getattr(error, 'provider_name', 'unknown')} "
            f"code={getattr(error, 'error_code', 'unknown')}",
            file=sys.stderr,
            flush=True,
        )
    print(_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL, file=sys.stderr, flush=True)


def _route_identity(model: object) -> tuple[str, str, str]:
    """Return the provider-account/model identity used for evidence joins."""
    return (
        str(getattr(model, "provider_name", None) or ""),
        str(getattr(model, "credential_name", None) or ""),
        str(getattr(model, "model_id", None) or ""),
    )


def _report_rows(
    discovered: Iterable[object],
    free_route_identities: frozenset[tuple[str, str, str]],
) -> list[dict[str, object]]:
    """Convert discovered models into policy rows without inferring evidence."""
    from scripts.ci import zdr_policy

    rows: list[dict[str, object]] = []
    for model in discovered:
        provider = str(getattr(model, "provider_name", None) or "")
        model_id = str(getattr(model, "model_id", None) or "")
        credential_key = str(getattr(model, "credential_name", None) or "")
        if not provider or not model_id or not credential_key:
            continue
        expected_credential = zdr_policy.PROVIDER_CREDENTIAL_NAMES.get(provider)
        if expected_credential != credential_key:
            # The policy parser will also reject mismatches. Omitting an
            # incomplete row here prevents fallback defaults from manufacturing
            # credential evidence that discovery did not provide.
            continue
        base_url = str(
            getattr(model, "chat_base_url", None)
            or zdr_policy.PROVIDER_BASE_URLS[provider]
        )
        auth_scheme = str(
            getattr(model, "auth_scheme", None)
            or zdr_policy.PROVIDER_AUTH_SCHEMES[provider]
        )
        rows.append(
            {
                "provider": provider,
                "model": model_id,
                "agent_id": str(
                    getattr(model, "agent_id", None)
                    or f"{provider}_{model_id}"
                ),
                "is_free": _route_identity(model) in free_route_identities,
                "prompt_price_per_1k": getattr(model, "prompt_price_per_1k", None),
                "completion_price_per_1k": getattr(
                    model, "completion_price_per_1k", None
                ),
                "currency_code": getattr(model, "currency_code", None),
                "base_url": base_url,
                "credential_key": credential_key,
                "auth_scheme": auth_scheme,
            }
        )
    return rows


def _write_json(path: str, payload: object) -> None:
    """Write deterministic UTF-8 JSON evidence."""
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _registered_provider_credentials(registered: Iterable[str]) -> frozenset[str]:
    """Return provider credentials actually copied into this bootstrap KV."""
    from scripts.ci.zdr_policy import PROVIDER_CREDENTIAL_NAMES

    provider_credentials = frozenset(PROVIDER_CREDENTIAL_NAMES.values())
    return frozenset(registered) & provider_credentials


def _filter_current_bootstrap_scope(
    models: Iterable[object], registered_credentials: frozenset[str]
) -> list[object]:
    """Exclude models backed only by credentials retained from another context."""
    return [
        model
        for model in models
        if str(getattr(model, "credential_name", None) or "")
        in registered_credentials
    ]


def main(argv: list[str] | None = None) -> int:
    """Bootstrap credentials, admit evidence-eligible models, and serve.

    No synthetic generation probe participates in route admission. The
    ``--preflight-out`` artifact is retained for workflow compatibility and
    records that the former heuristic probe layer is disabled; the shell-level
    post-start gateway request remains an end-to-end service readiness check,
    not a route-ranking mechanism.
    """
    parser = argparse.ArgumentParser(
        description="Serve the contextual-orchestrator review sidecar."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--auth-token",
        default="",
        help="Explicit bearer token; otherwise resolve it from the credential KV",
    )
    parser.add_argument(
        "--discovery-out", required=True, help="Path to write discovery evidence"
    )
    parser.add_argument(
        "--catalog-out", required=True, help="Path to write admitted agents"
    )
    parser.add_argument(
        "--report-out", required=True, help="Path to write admission evidence"
    )
    parser.add_argument(
        "--preflight-out",
        required=True,
        help="Path to write the no-synthetic-preflight audit record",
    )
    parser.add_argument(
        "--zdr-endpoints",
        default=None,
        help="Optional OpenRouter ZDR endpoint-evidence JSON path",
    )
    parser.add_argument("--require-zdr", action="store_true")
    parser.add_argument("--pool", choices=("free", "auto"), default="free")
    args = parser.parse_args(argv)

    from contextual_orchestrator.credentials import get_credential
    from contextual_orchestrator.model_discovery import (
        discover_all_models,
        free_discovered_models,
        general_free_serving_candidates,
        is_discovered_chat_candidate,
        is_routable_discovered_model,
    )
    from contextual_orchestrator.orchestrator import ModelClient, TaskOrchestrator, load_agents
    from contextual_orchestrator.review_gateway import (
        REVIEW_AUTH_CREDENTIAL_NAME,
        register_review_credentials,
    )
    from contextual_orchestrator.server import SecurityConfig, serve
    from scripts.ci.contextual_orchestrator_review_policy import (
        PolicyError,
        _load_zdr_endpoints,
        build_zdr_prioritized_catalog,
        parse_discovery_report,
    )

    registered = register_review_credentials(os.environ)
    registered_credentials = _registered_provider_credentials(registered)
    if not registered_credentials:
        raise SystemExit("review sidecar requires at least one provider credential")

    auth_token = args.auth_token or get_credential(REVIEW_AUTH_CREDENTIAL_NAME)
    if not auth_token:
        raise SystemExit(
            "review sidecar requires an explicit --auth-token or the "
            f"KV credential {REVIEW_AUTH_CREDENTIAL_NAME!r}"
        )

    try:
        discovered, discovery_errors = discover_all_models()
    except Exception as exc:  # pragma: no cover - provider/networking failure is runtime-only
        raise SystemExit(f"review sidecar discovery failed: {type(exc).__name__}") from None
    _log_discovery_errors(discovery_errors)

    current_scope_models = _filter_current_bootstrap_scope(
        discovered, registered_credentials
    )
    routable_models = [
        model
        for model in current_scope_models
        if is_routable_discovered_model(model)
    ]
    free_models = list(free_discovered_models(routable_models))
    free_route_identities = frozenset(
        _route_identity(model) for model in free_models
    )

    if args.pool == "free":
        selected_models = list(general_free_serving_candidates(routable_models))
    else:
        selected_models = [
            model
            for model in routable_models
            if is_discovered_chat_candidate(model)
        ]

    if not selected_models:
        raise SystemExit(
            f"review sidecar discovered no eligible models; orchestrator/{args.pool} "
            "would fail closed"
        )

    discovery_rows = _report_rows(selected_models, free_route_identities)
    _write_json(args.discovery_out, {"models": discovery_rows})
    try:
        normalized_rows = parse_discovery_report({"models": discovery_rows})
        result = build_zdr_prioritized_catalog(
            normalized_rows,
            zdr_endpoints=_load_zdr_endpoints(args.zdr_endpoints),
            require_zdr=args.require_zdr,
            pool=args.pool,
        )
    except PolicyError as exc:
        raise SystemExit(f"review sidecar admission failed: {exc}") from None

    Path(args.catalog_out).write_text(
        json.dumps({"agents": result["agents"]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_json(args.report_out, result["report"])
    _write_json(
        args.preflight_out,
        {
            "contract": "no-synthetic-preflight-v1",
            "selection_contract": "evidence-admission-only-v1",
            "probed_count": 0,
            "route_filtering_from_probe": False,
            "reason": (
                "synthetic generation probes and fixed token/escalation budgets "
                "were removed from candidate admission"
            ),
        },
    )

    agents = load_agents(args.catalog_out)
    if not agents:
        raise SystemExit("review sidecar admission produced no loadable agents")

    # Do not inject a CI-specific token budget, sampling parameter, retry count,
    # or route priority. Those values must come from contextual-orchestrator's
    # governed serving contract rather than from this workflow wrapper.
    orchestrator = TaskOrchestrator(agents, client=ModelClient())
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(auth_token=auth_token),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
