"""Serve the librarian-controlled ``orchestrator/free`` review sidecar.

This launcher runs with the vendored ``contextual-orchestrator`` source on
``PYTHONPATH``; it deliberately mirrors ``contextual_orchestrator.review_gateway``
(the org's reference CI sidecar) so that the five provider credentials and the
gateway bearer token enter the process-local KV exactly once, in the same
process that performs model discovery and serves requests. Provincial
credentials never cross a process boundary and are never read from ``os.environ``
at request time — env is bootstrap transport into the KV.

The difference from ``review_gateway.main()`` is the agent pool: discovery runs
in-process (so the KV-backed credentials are visible to it), the zero-cost
("free") routes are collected into a report, and
``scripts/ci/contextual_orchestrator_review_policy.py`` turns that report into a
ZDR-prioritized, provider-family-diverse catalog for ``orchestrator/free``.
Keeping the decision logic in that stdlib-only module lets every branch of the
ZDR policy be tested offline in this repository while ``orchestrator/free``
still resolves from authentically zero-priced models discovered by the
orchestrator itself. This module is exercised at CI runtime only.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from typing import Any


# The vendored server's generic 64 KiB default is intentionally conservative.
# This loopback, bearer-authenticated review sidecar accepts OpenAI's image-input
# request ceiling so repository context can include inline image inputs.
REVIEW_MAX_BODY_BYTES = 512 * 1024 * 1024
# Keep ordinary review turns portable across small zero-cost providers. The
# failing Strix run used 32768 for every call, including its two-word warm-up.
REVIEW_MAX_OUTPUT_TOKENS = 4096
# Provider-neutral sampling: several modern endpoints reject non-default
# temperatures, while 1.0 is the OpenAI-compatible default.
REVIEW_TEMPERATURE = 1.0
# A selected route that cannot answer within ten seconds is not reliable enough
# for a required CI gate. Four-route batches let discovery try a broader but
# still finite catalog while keeping the worst-case provider wait below the
# sidecar's three-minute readiness deadline.
REVIEW_PREFLIGHT_TIMEOUT_SECONDS = 10
REVIEW_PREFLIGHT_BATCH_SIZE = 4
REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES = 24
REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT = 8


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
    return not modalities or "text" in {
        str(modality).casefold() for modality in modalities
    }


def _route_identity(model: object) -> tuple[str, str]:
    """Return the provider/model identity used to bind price evidence."""

    return (
        str(getattr(model, "provider_name", None) or ""),
        str(getattr(model, "model_id", None) or ""),
    )


def _report_rows(
    discovered: list[object], free_route_identities: frozenset[tuple[str, str]]
) -> list[dict[str, object]]:
    """Convert in-process discovered models into price-evidenced report rows.

    Only routes the orchestrator itself marks zero-priced (whole-prompt and
    whole-completion published price equal to zero; never name-implied) are
    admitted to the ``orchestrator/free`` pool. Provider routing metadata is
    read from the discovered model when present and otherwise falls back to the
    org ZDR policy table (``scripts/ci/zdr_policy.py``).

    Args:
        discovered: Selected ``discover_all_models()`` result.
        free_route_identities: Routes the orchestrator attested as zero-priced.

    Returns:
        Price-evidenced rows shaped for
        ``contextual_orchestrator_review_policy.parse_discovery_report``.
    """
    from scripts.ci import zdr_policy

    rows: list[dict[str, object]] = []
    for model in discovered:
        provider = str(getattr(model, "provider_name", None) or "")
        model_id = str(getattr(model, "model_id", None) or "")
        if not provider or not model_id:
            continue
        base_url = str(
            getattr(model, "chat_base_url", None)
            or zdr_policy.PROVIDER_BASE_URLS[provider]
        )
        credential_key = str(
            getattr(model, "credential_name", None)
            or zdr_policy.PROVIDER_CREDENTIAL_NAMES[provider]
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
                    getattr(model, "agent_id", None) or f"{provider}_{model_id}"
                ),
                "is_free": (provider, model_id) in free_route_identities,
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


def _sanitized_discovery_errors(errors: list[object]) -> list[dict[str, str]]:
    """Return stable provider discovery failures without response text."""
    rows: list[dict[str, str]] = []
    for error in errors:
        provider = str(getattr(error, "provider_name", ""))
        code = str(getattr(error, "error_code", ""))
        rows.append(
            {
                "provider": provider
                if provider.isidentifier() and len(provider) <= 64
                else "unknown",
                "error_code": code
                if code.isidentifier() and len(code) <= 64
                else "provider_error",
            }
        )
    return rows


def _require_complete_discovery(
    discovered: list[object], errors: list[object], output_path: str
) -> list[object]:
    """Return a complete catalog or persist sanitized failure evidence."""
    if not errors:
        return discovered
    _write_json(
        output_path,
        {
            "complete": False,
            "models": [],
            "errors": _sanitized_discovery_errors(errors),
        },
    )
    raise SystemExit("review sidecar discovery incomplete")


def _preflight_review_agents(
    agents: list[object], *, client: Any
) -> tuple[list[object], dict[str, object]]:
    """Probe each route with the runtime request contract and keep ready routes.

    The report deliberately records only stable route identity, a bounded
    exception class name, and an optional numeric HTTP status. Provider response
    bodies, exception messages, URLs, prompts, and credentials are never copied
    into evidence.

    Args:
        agents: Selected zero-cost model agents.
        client: Vendored ``ModelClient``-compatible transport.

    Returns:
        A pair of viable agents and a sanitized preflight report.

    Raises:
        ReviewPreflightError: If no provider route returns usable text.
    """
    viable: list[object] = []
    routes: list[dict[str, object]] = []
    for agent in agents:
        row: dict[str, object] = {
            "agent_id": str(getattr(agent, "id", "")),
            "provider": str(getattr(agent, "provider_name", "") or "unknown"),
            "model": str(getattr(agent, "model", "")),
        }
        payload: dict[str, object] = {
            "model": getattr(agent, "model", ""),
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Reply with just 'OK'."},
            ],
            "temperature": REVIEW_TEMPERATURE,
            "max_tokens": REVIEW_MAX_OUTPUT_TOKENS,
            "stream": False,
        }
        try:
            response = client.proxy_send_once(agent, "chat/completions", payload)
        except Exception as exc:  # noqa: BLE001 - sanitize at the provider boundary
            row["status"] = "rejected"
            error_type = type(exc).__name__
            row["error_type"] = (
                error_type
                if error_type.isidentifier() and len(error_type) <= 64
                else "ProviderError"
            )
            http_status = _safe_http_status(exc)
            if http_status is not None:
                row["http_status"] = http_status
            routes.append(row)
            continue
        if not _chat_response_has_text(response):
            row["status"] = "rejected"
            row["error_type"] = "InvalidChatResponse"
            routes.append(row)
            continue
        row["status"] = "ready"
        routes.append(row)
        viable.append(agent)

    report: dict[str, object] = {
        "contract": "strix-plain-chat-preflight-v1",
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


def _preflight_with_fallback(
    primary_agents: list[object], fallback_agents: list[object], *, client: Any
) -> tuple[list[object], dict[str, object], bool]:
    """Use the priced catalog only after every primary route rejects."""
    try:
        viable, report = _preflight_review_agent_batches(primary_agents, client=client)
        return viable, report, False
    except ReviewPreflightError as primary_error:
        if not fallback_agents:
            raise
        try:
            viable, report = _preflight_review_agent_batches(
                fallback_agents, client=client
            )
        except ReviewPreflightError as fallback_error:
            fallback_error.report["primary_attempt"] = primary_error.report
            raise
        report["primary_attempt"] = primary_error.report
        report["fallback_reason"] = "primary_routes_unavailable"
        return viable, report, True


def _preflight_review_agent_batches(
    agents: list[object], *, client: Any
) -> tuple[list[object], dict[str, object]]:
    """Probe bounded concurrent batches until one batch contains a ready route."""
    attempted_routes: list[dict[str, object]] = []
    attempted_count = 0
    for offset in range(0, len(agents), REVIEW_PREFLIGHT_BATCH_SIZE):
        batch = agents[offset : offset + REVIEW_PREFLIGHT_BATCH_SIZE]
        with ThreadPoolExecutor(max_workers=len(batch)) as executor:
            futures = [
                executor.submit(_preflight_review_agents, [agent], client=client)
                for agent in batch
            ]
            viable: list[object] = []
            for future in futures:
                try:
                    route_viable, route_report = future.result()
                except ReviewPreflightError as exc:
                    route_viable = []
                    route_report = exc.report
                viable.extend(route_viable)
                attempted_routes.extend(route_report["routes"])
                attempted_count += int(route_report["probed_count"])
        if viable:
            return viable, {
                "contract": "strix-plain-chat-preflight-v1",
                "probed_count": attempted_count,
                "ready_count": len(viable),
                "rejected_count": attempted_count - len(viable),
                "routes": attempted_routes,
                "batch_size": REVIEW_PREFLIGHT_BATCH_SIZE,
            }
    report: dict[str, object] = {
        "contract": "strix-plain-chat-preflight-v1",
        "probed_count": attempted_count,
        "ready_count": 0,
        "rejected_count": attempted_count,
        "routes": attempted_routes,
        "batch_size": REVIEW_PREFLIGHT_BATCH_SIZE,
    }
    raise ReviewPreflightError(
        "no provider route passed the Strix plain-chat preflight", report
    )


def _write_json(path: str, payload: object) -> None:
    """Write one deterministic UTF-8 JSON evidence file."""
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _bounded_primary_catalog_limit(
    requested_limit: int, *, pool: str, has_free_rows: bool
) -> int:
    """Return the primary-stage route limit within one startup budget."""
    if requested_limit < 1:
        raise ValueError("ORCHESTRATOR_CATALOG_LIMIT must be positive")
    total_limit = min(requested_limit, REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES)
    if pool == "auto" and has_free_rows:
        return min(total_limit, REVIEW_PREFLIGHT_PRIMARY_ROUTE_LIMIT)
    return total_limit


def _bounded_fallback_catalog_limit(requested_limit: int, *, primary_count: int) -> int:
    """Return remaining priced-fallback capacity after primary selection."""
    if requested_limit < 1:
        raise ValueError("ORCHESTRATOR_CATALOG_LIMIT must be positive")
    total_limit = min(requested_limit, REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES)
    if primary_count < 0 or primary_count > total_limit:
        raise ValueError("primary route count exceeds the preflight budget")
    return total_limit - primary_count


def _catalog_family_cap() -> int:
    """Return the configured family cap without narrowing the bounded default."""
    return int(
        os.environ.get(
            "ORCHESTRATOR_CATALOG_FAMILY_CAP",
            str(REVIEW_PREFLIGHT_MAX_TOTAL_ROUTES),
        )
    )


def _with_discovery_counts(
    report: dict[str, object], rows: list[dict[str, Any]]
) -> dict[str, object]:
    """Copy a stage report while restoring full discovery-tier counts."""
    enriched = dict(report)
    enriched.update(
        {
            "total_routes": len(rows),
            "total_free_routes": sum(
                row.get("cost_evidence") == "free" for row in rows
            ),
            "total_priced_routes": sum(
                row.get("cost_evidence") == "priced" for row in rows
            ),
            "total_unknown_routes": sum(
                row.get("cost_evidence") == "unknown" for row in rows
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
    """Bootstrap the KV, discover and preflight free models, then serve.

    Args:
        argv: CLI arguments (``--host``, ``--port``, ``--auth-token``,
            ``--catalog-out``, ``--report-out``, ``--preflight-out``,
            ``--discovery-out``, ``--zdr-endpoints``).

    Returns:
        0 when the server exits cleanly; 1 on any configuration error.

    Raises:
        SystemExit: If the vendored library is missing, no provider credential
            is in the KV, no free model was discovered, no route passes runtime
            preflight, or no auth token is available — the sidecar must fail
            closed rather than boot a mock or unaudited pool.
    """
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
    parser.add_argument("--pool", choices=("free", "auto"), default="free")
    args = parser.parse_args(argv)

    from contextual_orchestrator.credentials import get_credential
    from contextual_orchestrator.chat_capability import is_general_chat_agent_model_id
    from contextual_orchestrator.model_discovery import (
        discover_all_models,
        free_discovered_models,
    )
    from contextual_orchestrator.orchestrator import (
        ModelClient,
        TaskOrchestrator,
        load_agents,
    )
    from contextual_orchestrator.review_gateway import (
        REVIEW_AUTH_CREDENTIAL_NAME,
        register_review_credentials,
    )
    from contextual_orchestrator.server import SecurityConfig, serve
    from scripts.ci.contextual_orchestrator_review_policy import (
        PolicyError,
        _load_zdr_endpoints,
        build_zdr_prioritized_catalog,
        is_zdr_model,
        parse_discovery_report,
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
    except (
        Exception
    ) as exc:  # pragma: no cover - provider/networking failure is runtime-only
        raise SystemExit(f"review sidecar discovery failed: {exc}") from exc
    discovered = _require_complete_discovery(
        list(discovered), list(discovery_errors), args.discovery_out
    )
    free_models = list(free_discovered_models(discovered)) if discovered else []
    free_route_identities = frozenset(_route_identity(model) for model in free_models)
    selected_models = []
    for model in discovered or []:
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
    _write_json(
        args.discovery_out,
        {"complete": True, "models": rows, "errors": []},
    )
    zdr_endpoints = _load_zdr_endpoints(args.zdr_endpoints)
    normalized_rows = parse_discovery_report({"models": rows})
    free_rows = [row for row in normalized_rows if row.get("cost_evidence") == "free"]
    priced_rows = [
        row for row in normalized_rows if row.get("cost_evidence") == "priced"
    ]
    admitted_free_rows = _zdr_admitted_rows(
        free_rows,
        require_zdr=args.require_zdr,
        zdr_endpoints=zdr_endpoints,
        checker=is_zdr_model,
    )
    admitted_priced_rows = _zdr_admitted_rows(
        priced_rows,
        require_zdr=args.require_zdr,
        zdr_endpoints=zdr_endpoints,
        checker=is_zdr_model,
    )
    requested_catalog_limit = int(os.environ.get("ORCHESTRATOR_CATALOG_LIMIT", "24"))
    primary_limit = _bounded_primary_catalog_limit(
        requested_catalog_limit, pool=args.pool, has_free_rows=bool(admitted_free_rows)
    )
    primary_rows = (
        (admitted_free_rows or admitted_priced_rows)
        if args.pool == "auto"
        else normalized_rows
    )
    result = build_zdr_prioritized_catalog(
        primary_rows,
        limit=primary_limit,
        family_cap=_catalog_family_cap(),
        zdr_endpoints=zdr_endpoints,
        require_zdr=args.require_zdr,
        pool=args.pool,
    )
    result["report"] = _with_discovery_counts(result["report"], normalized_rows)
    Path(args.catalog_out).write_text(
        json.dumps({"agents": result["agents"]}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_json(args.report_out, result["report"])

    agents = load_agents(args.catalog_out)
    primary_report = result["report"]
    fallback_result = None
    fallback_agents: list[object] = []
    fallback_limit = _bounded_fallback_catalog_limit(
        requested_catalog_limit, primary_count=len(result["agents"])
    )
    if (
        args.pool == "auto"
        and admitted_free_rows
        and admitted_priced_rows
        and fallback_limit
    ):
        try:
            fallback_result = build_zdr_prioritized_catalog(
                admitted_priced_rows,
                limit=fallback_limit,
                family_cap=_catalog_family_cap(),
                zdr_endpoints=zdr_endpoints,
                require_zdr=args.require_zdr,
                pool="auto",
            )
        except PolicyError:
            fallback_result = None
        if fallback_result is not None:
            fallback_result["report"] = _with_discovery_counts(
                fallback_result["report"], normalized_rows
            )
            fallback_result["report"]["primary_selected_count"] = primary_report[
                "selected_count"
            ]
            fallback_result["report"]["primary_selection"] = primary_report["selected"]
            fallback_agents = _load_temporary_agents(
                f"{args.catalog_out}.priced",
                fallback_result["agents"],
                loader=load_agents,
            )
    client = ModelClient(
        timeout=REVIEW_PREFLIGHT_TIMEOUT_SECONDS,
        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
        max_retries=0,
        temperature=REVIEW_TEMPERATURE,
    )
    try:
        agents, preflight_report, fallback_used = _preflight_with_fallback(
            agents, fallback_agents, client=client
        )
    except ReviewPreflightError as exc:
        _write_json(args.preflight_out, exc.report)
        raise SystemExit(f"review sidecar preflight failed: {exc}") from None
    if fallback_used and fallback_result is not None:
        Path(args.catalog_out).write_text(
            json.dumps({"agents": fallback_result["agents"]}, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
        result = fallback_result
        result["report"]["fallback_reason"] = "primary_routes_unavailable"
        _write_json(args.report_out, result["report"])
    _write_json(args.preflight_out, preflight_report)

    client = ModelClient(
        max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS,
        temperature=REVIEW_TEMPERATURE,
    )
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
