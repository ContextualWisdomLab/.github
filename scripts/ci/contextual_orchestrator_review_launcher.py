"""Serve the librarian-controlled ``orchestrator/free`` review sidecar.

The launcher discovers zero-priced routes through contextual-orchestrator,
records bounded admission evidence, performs one provider-default compatibility
observation per route, and then serves the admitted pool. Provider/model routing,
compute allocation, retry policy, and test-time-compute remain owner-side
contextual-orchestrator responsibilities rather than repository heuristics.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from scripts.ci.contextual_orchestrator_review_policy import FREE_POOL_CREDENTIAL_NAMES


# The vendored server's generic 64 KiB default is intentionally conservative.
# This loopback, bearer-authenticated review sidecar accepts OpenAI's image-input
# request ceiling so repository context can include inline image inputs.
REVIEW_MAX_BODY_BYTES = 512 * 1024 * 1024


class ReviewPreflightError(RuntimeError):
    """Raised when no selected free provider route is ready for review traffic."""

    def __init__(self, message: str, report: dict[str, object]) -> None:
        """Store the sanitized route report alongside the bounded error message."""
        super().__init__(message)
        self.report = report


def _has_text_output(model: object) -> bool:
    """Return whether a discovered model can emit text responses."""
    modalities = getattr(model, "output_modalities", None)
    if modalities is None:
        return False
    if isinstance(modalities, str):
        modalities = (modalities,)
    return not modalities or "text" in {str(modality).casefold() for modality in modalities}


_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL = "discovery_diagnostics_complete"


def _log_discovery_errors(errors: list[object]) -> None:
    """Print one bounded, secret-free diagnostic per provider discovery failure.

    The trailing sentinel lets the shell-side sanitizer prove that every
    discovery diagnostic preceding it has been drained without depending on a
    wall-clock delay or byte-count heuristic.
    """
    for error in errors:
        print(
            f"provider_discovery_failed provider={getattr(error, 'provider_name', 'unknown')} "
            f"code={getattr(error, 'error_code', 'unknown')}",
            file=sys.stderr,
            flush=True,
        )
    print(_DISCOVERY_DIAGNOSTICS_COMPLETE_SENTINEL, file=sys.stderr, flush=True)


def _routable_discovered_models(discovered: list[object] | None) -> list[object]:
    """Drop evidence-only discovery rows before any live-serving selection."""
    return [model for model in (discovered or []) if not getattr(model, "evidence_only", False)]


def _route_identity(model: object) -> tuple[str, str]:
    """Return the provider/model identity used to bind price evidence."""
    return (
        str(getattr(model, "provider_name", None) or ""),
        str(getattr(model, "model_id", None) or ""),
    )


def _report_rows(
    discovered: list[object], free_route_identities: frozenset[tuple[str, str]]
) -> list[dict[str, object]]:
    """Convert discovered models into price-evidenced policy report rows."""
    from scripts.ci import zdr_policy

    rows: list[dict[str, object]] = []
    for model in discovered:
        provider = str(getattr(model, "provider_name", None) or "")
        model_id = str(getattr(model, "model_id", None) or "")
        if not provider or not model_id:
            continue
        base_url = str(
            getattr(model, "chat_base_url", None) or zdr_policy.PROVIDER_BASE_URLS[provider]
        )
        credential_key = str(
            getattr(model, "credential_name", None)
            or zdr_policy.PROVIDER_CREDENTIAL_NAMES[provider]
        )
        auth_scheme = str(
            getattr(model, "auth_scheme", None) or zdr_policy.PROVIDER_AUTH_SCHEMES[provider]
        )
        rows.append(
            {
                "provider": provider,
                "model": model_id,
                "agent_id": str(
                    getattr(model, "agent_id", None) or f"{provider}_{model_id}"
                ),
                "is_free": (provider, model_id) in free_route_identities,
                "prompt_price_per_1k": getattr(model, "prompt_price_per_1k", None),
                "completion_price_per_1k": getattr(model, "completion_price_per_1k", None),
                "currency_code": getattr(model, "currency_code", None),
                "base_url": base_url,
                "credential_key": credential_key,
                "auth_scheme": auth_scheme,
            }
        )
    return rows


def _chat_response_has_text(response: object) -> bool:
    """Return whether an OpenAI-compatible response contains non-empty text."""
    if not isinstance(response, dict):
        return False
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    message = first.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    return isinstance(content, str) and bool(content.strip())


def _safe_http_status(exc: Exception) -> int | None:
    """Return one bounded HTTP status without persisting an exception message."""
    status = getattr(exc, "code", None)
    if type(status) is int and 100 <= status <= 599:
        return status
    return None


def _response_finish_reason(response: object) -> str | None:
    """Return a bounded ``finish_reason`` from an OpenAI-compatible response."""
    if not isinstance(response, dict):
        return None
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    finish_reason = first.get("finish_reason")
    if not isinstance(finish_reason, str) or not finish_reason:
        return None
    if len(finish_reason) > 32 or not all(
        character.isalnum() or character == "_" for character in finish_reason
    ):
        return "unknown"
    return finish_reason


def _record_provider_exception(row: dict[str, object], exc: Exception) -> None:
    """Record a bounded provider-exception classification without raw text."""
    row["status"] = "rejected"
    error_type = type(exc).__name__
    row["error_type"] = (
        error_type
        if error_type.isidentifier() and len(error_type) <= 64
        else "provider_error"
    )
    http_status = _safe_http_status(exc)
    if http_status is not None:
        row["http_status"] = http_status
    row.pop("finish_reason", None)
    row.pop("reasoning_without_content", None)


def _response_has_reasoning_without_content(response: object) -> bool:
    """Return whether reasoning exists while usable visible content does not."""
    if not isinstance(response, dict):
        return False
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0]
    if not isinstance(first, dict):
        return False
    message = first.get("message")
    if not isinstance(message, dict) or not message.get("reasoning"):
        return False
    return not _chat_response_has_text(response)


def _send_preflight_request(
    client: Any, agent: object, payload: dict[str, object]
) -> object:
    """Send one exact provider-default compatibility request exactly once."""
    return client.proxy_send_once(agent, "chat/completions", payload)


def _preflight_review_agent(
    agent: object, *, client: Any
) -> tuple[object | None, dict[str, object]]:
    """Observe one route once without allocating repository-side TTC policy."""
    row: dict[str, object] = {
        "agent_id": str(getattr(agent, "id", "")),
        "provider": str(getattr(agent, "provider_name", "") or "unknown"),
        "model": str(getattr(agent, "model", "")),
        "attempts": 1,
    }
    payload: dict[str, object] = {
        "model": getattr(agent, "model", ""),
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Reply with just 'OK'."},
        ],
        "stream": False,
    }
    try:
        response = _send_preflight_request(client, agent, payload)
    except Exception as exc:  # noqa: BLE001 - sanitize at provider boundary
        _record_provider_exception(row, exc)
        return None, row

    finish_reason = _response_finish_reason(response)
    reasoning_without_content = _response_has_reasoning_without_content(response)
    row["finish_reason"] = finish_reason or "unknown"
    row["reasoning_without_content"] = reasoning_without_content
    if _chat_response_has_text(response):
        row["status"] = "ready"
        return agent, row

    row["status"] = "rejected"
    if finish_reason == "length" or reasoning_without_content:
        row["error_type"] = "insufficient_preflight_evidence"
    else:
        row["error_type"] = "invalid_chat_response"
    return None, row


def _preflight_review_agents(
    agents: list[object], *, client: Any
) -> tuple[list[object], dict[str, object]]:
    """Probe admitted routes once with provider-account bounded concurrency.

    Independent provider accounts progress concurrently. Routes sharing one
    provider-account identity remain serial, and outcomes are restored to
    catalog order before publication so latency cannot become routing authority.
    """
    if not agents:
        report: dict[str, object] = {
            "contract": "strix-plain-chat-preflight-v2",
            "probed_count": 0,
            "ready_count": 0,
            "rejected_count": 0,
            "routes": [],
        }
        raise ReviewPreflightError(
            "no provider route passed the Strix plain-chat preflight", report
        )

    provider_lanes: dict[str, list[tuple[int, object]]] = {}
    for index, agent in enumerate(agents):
        provider_account = str(getattr(agent, "provider_name", "") or "unknown")
        provider_lanes.setdefault(provider_account, []).append((index, agent))

    def probe_lane(
        lane: list[tuple[int, object]],
    ) -> list[tuple[int, tuple[object | None, dict[str, object]]]]:
        """Probe one provider account serially while other accounts progress."""
        return [
            (index, _preflight_review_agent(agent, client=client))
            for index, agent in lane
        ]

    with ThreadPoolExecutor(
        max_workers=len(provider_lanes), thread_name_prefix="review-preflight"
    ) as executor:
        futures = [executor.submit(probe_lane, lane) for lane in provider_lanes.values()]
        indexed_outcomes = [
            indexed_outcome
            for future in futures
            for indexed_outcome in future.result()
        ]
    indexed_outcomes.sort(key=lambda item: item[0])
    outcomes = [outcome for _index, outcome in indexed_outcomes]

    viable: list[object] = []
    routes: list[dict[str, object]] = []
    for ready_agent, row in outcomes:
        routes.append(row)
        if ready_agent is not None:
            viable.append(ready_agent)

    report = {
        "contract": "strix-plain-chat-preflight-v2",
        "probed_count": len(agents),
        "ready_count": len(viable),
        "rejected_count": len(agents) - len(viable),
        "routes": routes,
    }
    if not viable:
        raise ReviewPreflightError(
            "no provider route passed the Strix plain-chat preflight", report
        )
    return viable, report


def _log_preflight_rejections(report: dict[str, object]) -> None:
    """Print bounded rejected-route diagnostics to stderr."""
    primary_attempt = report.get("primary_attempt")
    if isinstance(primary_attempt, dict):
        _log_preflight_rejections(primary_attempt)
    routes = report.get("routes")
    if not isinstance(routes, list):
        return
    for row in routes:
        if not isinstance(row, dict) or row.get("status") != "rejected":
            continue
        provider_value = row.get("provider")
        provider = (
            provider_value
            if isinstance(provider_value, str)
            and re.fullmatch(r"[a-z][a-z0-9_]{0,63}", provider_value)
            else "unknown"
        )
        error_type_value = row.get("error_type")
        error_type = (
            error_type_value
            if isinstance(error_type_value, str)
            and error_type_value.isidentifier()
            and len(error_type_value) <= 64
            else "UnknownError"
        )
        http_status = row.get("http_status")
        if (
            isinstance(http_status, int)
            and not isinstance(http_status, bool)
            and 100 <= http_status <= 599
        ):
            print(
                f"preflight_route_rejected provider={provider} "
                f"error_type={error_type} http_status={http_status}",
                file=sys.stderr,
            )
        else:
            print(
                f"preflight_route_rejected provider={provider} error_type={error_type}",
                file=sys.stderr,
            )


def _write_json(path: str, payload: object) -> None:
    """Write one deterministic UTF-8 JSON evidence file."""
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _with_discovery_counts(
    report: dict[str, object],
    rows: list[dict[str, Any]],
    *,
    provider_account: Any,
) -> dict[str, object]:
    """Copy a stage report while restoring discovery-wide route counts."""
    free_rows = [row for row in rows if row.get("cost_evidence") == "free"]
    free_pool_rows = [
        row
        for row in free_rows
        if isinstance(row.get("credential_key"), str)
        and row["credential_key"] in FREE_POOL_CREDENTIAL_NAMES
    ]
    enriched = dict(report)
    enriched.update(
        {
            "total_routes": len(rows),
            "total_free_routes": len(free_rows),
            "total_priced_routes": sum(
                row.get("cost_evidence") == "priced" for row in rows
            ),
            "total_unknown_routes": sum(
                row.get("cost_evidence") == "unknown" for row in rows
            ),
            "free_account_diversity": len(
                {provider_account(str(row["provider"])) for row in free_rows}
            ),
            "free_pool_admitted_routes": len(free_pool_rows),
            "free_pool_excluded_source_count": len(free_rows) - len(free_pool_rows),
            "free_pool_account_diversity": len(
                {
                    provider_account(str(row["provider"]))
                    for row in free_pool_rows
                }
            ),
        }
    )
    return enriched


def _zdr_admitted_rows(
    rows: list[dict[str, Any]],
    *,
    require_zdr: bool,
    zdr_endpoints: frozenset[str],
    checker: Any,
) -> list[dict[str, Any]]:
    """Return rows that can enter the selected privacy boundary."""
    if not require_zdr:
        return list(rows)
    return [
        row
        for row in rows
        if checker(
            str(row["provider"]),
            model=str(row["model"]),
            zdr_endpoints=zdr_endpoints,
        )
    ]


def _load_temporary_agents(
    path: str, catalog_agents: list[dict[str, Any]], *, loader: Any
) -> list[object]:
    """Load one transient catalog and remove it on every exit path."""
    catalog_path = Path(path)
    _write_json(str(catalog_path), {"agents": catalog_agents})
    try:
        return list(loader(str(catalog_path)))
    finally:
        catalog_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """Bootstrap credentials, discover/preflight free models, and serve."""
    parser = argparse.ArgumentParser(
        description="Serve the contextual-orchestrator review sidecar."
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument(
        "--auth-token",
        default="",
        help="Explicit bearer token; else resolve from the KV",
    )
    parser.add_argument(
        "--discovery-out",
        required=True,
        help="Path to write the free-only discovery report JSON",
    )
    parser.add_argument(
        "--catalog-out", required=True, help="Path to write the agents catalog JSON"
    )
    parser.add_argument(
        "--report-out", required=True, help="Path to write the policy evidence JSON"
    )
    parser.add_argument(
        "--preflight-out",
        required=True,
        help="Path to write sanitized runtime preflight JSON",
    )
    parser.add_argument(
        "--zdr-endpoints",
        default=None,
        help="Optional OpenRouter /api/v1/endpoints/zdr JSON path",
    )
    parser.add_argument("--require-zdr", action="store_true")
    parser.add_argument("--pool", choices=("free",), default="free")
    args = parser.parse_args(argv)

    from contextual_orchestrator.chat_capability import is_general_chat_agent_model_id
    from contextual_orchestrator.credentials import get_credential
    from contextual_orchestrator.model_discovery import (
        discover_all_models,
        free_discovered_models,
    )
    from contextual_orchestrator.orchestrator import ModelClient, TaskOrchestrator, load_agents
    from contextual_orchestrator.review_gateway import (
        REVIEW_AUTH_CREDENTIAL_NAME,
        register_review_credentials,
    )
    from contextual_orchestrator.server import SecurityConfig, serve
    from scripts.ci.contextual_orchestrator_review_policy import (
        _load_zdr_endpoints,
        build_zdr_prioritized_catalog,
        parse_discovery_report,
        provider_account,
    )

    registered = register_review_credentials(os.environ)
    auth_token = args.auth_token or get_credential(REVIEW_AUTH_CREDENTIAL_NAME)
    if not auth_token:
        raise SystemExit(
            "review sidecar requires an explicit --auth-token or the "
            f"KV credential {REVIEW_AUTH_CREDENTIAL_NAME!r}"
        )
    if not any(
        name.startswith(("BYTEZ_", "NVIDIA_", "OPENROUTER_", "OPENAI_"))
        for name in registered
    ):
        raise SystemExit(
            "review sidecar requires at least one provider credential in the KV"
        )

    try:
        discovered, discovery_errors = discover_all_models()
    except Exception as exc:  # pragma: no cover - provider/networking failure is runtime-only
        raise SystemExit(f"review sidecar discovery failed: {exc}") from exc
    _log_discovery_errors(discovery_errors)
    routable_discovered = _routable_discovered_models(discovered)
    free_models = (
        list(free_discovered_models(routable_discovered))
        if routable_discovered
        else []
    )
    free_route_identities = frozenset(_route_identity(model) for model in free_models)
    selected_models = []
    for model in routable_discovered:
        model_id = getattr(model, "model_id", "")
        if not is_general_chat_agent_model_id(model_id) or not _has_text_output(model):
            continue
        if args.pool == "free" and _route_identity(model) not in free_route_identities:
            continue
        selected_models.append(model)
    if not selected_models:
        raise SystemExit(
            f"review sidecar discovered no eligible models; orchestrator/{args.pool} would fail closed"
        )

    rows = _report_rows(selected_models, free_route_identities)
    _write_json(args.discovery_out, {"models": rows})
    zdr_endpoints = _load_zdr_endpoints(args.zdr_endpoints)
    normalized_rows = parse_discovery_report({"models": rows})
    result = build_zdr_prioritized_catalog(
        normalized_rows,
        zdr_endpoints=zdr_endpoints,
        require_zdr=args.require_zdr,
        pool=args.pool,
    )
    result["report"] = _with_discovery_counts(
        result["report"], normalized_rows, provider_account=provider_account
    )
    Path(args.catalog_out).write_text(
        json.dumps({"agents": result["agents"]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_json(args.report_out, result["report"])

    agents = load_agents(args.catalog_out)
    client = ModelClient(timeout=None, max_retries=0)
    try:
        agents, preflight_report = _preflight_review_agents(agents, client=client)
    except ReviewPreflightError as exc:
        _write_json(args.preflight_out, exc.report)
        _log_preflight_rejections(exc.report)
        raise SystemExit(f"review sidecar preflight failed: {exc}") from None
    _write_json(args.preflight_out, preflight_report)

    client = ModelClient(timeout=None, max_retries=0)
    orchestrator = TaskOrchestrator(agents, client=client)
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(
            auth_token=auth_token,
            max_body_bytes=REVIEW_MAX_BODY_BYTES,
        ),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
