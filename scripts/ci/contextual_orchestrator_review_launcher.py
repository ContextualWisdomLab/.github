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
# Strix verifies connectivity with one tiny plain-chat request before scanning.
REVIEW_PREFLIGHT_MAX_OUTPUT_TOKENS = 16


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


def _free_report_rows(discovered: list[object]) -> list[dict[str, object]]:
    """Convert in-process discovered models into free-only report rows.

    Only routes the orchestrator itself marks zero-priced (whole-prompt and
    whole-completion published price equal to zero; never name-implied) are
    admitted to the ``orchestrator/free`` pool. Provider routing metadata is
    read from the discovered model when present and otherwise falls back to the
    org ZDR policy table (``scripts/ci/zdr_policy.py``).

    Args:
        discovered: ``discover_all_models()`` result (the free subset).

    Returns:
        Free-only rows shaped for
        ``contextual_orchestrator_review_policy.parse_discovery_report``.
    """
    from scripts.ci import zdr_policy

    rows: list[dict[str, object]] = []
    for model in discovered:
        provider = str(getattr(model, "provider_name", None) or "")
        model_id = str(getattr(model, "model_id", None) or "")
        if not provider or not model_id:
            continue
        base_url = str(getattr(model, "chat_base_url", None) or zdr_policy.PROVIDER_BASE_URLS[provider])
        credential_key = str(
            getattr(model, "credential_name", None) or zdr_policy.PROVIDER_CREDENTIAL_NAMES[provider]
        )
        auth_scheme = str(
            getattr(model, "auth_scheme", None) or zdr_policy.PROVIDER_AUTH_SCHEMES[provider]
        )
        rows.append(
            {
                "provider": provider,
                "model": model_id,
                "agent_id": str(getattr(model, "agent_id", None) or f"{provider}_{model_id}"),
                "is_free": True,
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


def _preflight_review_agents(
    agents: list[object], *, client: Any
) -> tuple[list[object], dict[str, object]]:
    """Probe each route with Strix's plain-chat warm-up and keep ready routes.

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
            "max_tokens": REVIEW_PREFLIGHT_MAX_OUTPUT_TOKENS,
            "stream": False,
        }
        try:
            response = client.proxy_send_once(agent, "chat/completions", payload)
        except Exception as exc:  # noqa: BLE001 - sanitize at the provider boundary
            row["status"] = "rejected"
            error_type = type(exc).__name__
            row["error_type"] = (
                error_type if error_type.isidentifier() and len(error_type) <= 64 else "ProviderError"
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


def _write_json(path: str, payload: object) -> None:
    """Write one deterministic UTF-8 JSON evidence file."""
    Path(path).write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


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
    parser = argparse.ArgumentParser(description="Serve the contextual-orchestrator review sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--auth-token", default="", help="Explicit bearer token; else resolve from the KV")
    parser.add_argument("--discovery-out", required=True, help="Path to write the free-only discovery report JSON")
    parser.add_argument("--catalog-out", required=True, help="Path to write the agents catalog JSON")
    parser.add_argument("--report-out", required=True, help="Path to write the policy evidence JSON")
    parser.add_argument("--preflight-out", required=True, help="Path to write sanitized runtime preflight JSON")
    parser.add_argument("--zdr-endpoints", default=None, help="Optional OpenRouter /api/v1/endpoints/zdr JSON path")
    parser.add_argument("--require-zdr", action="store_true")
    args = parser.parse_args(argv)

    from contextual_orchestrator.credentials import get_credential
    from contextual_orchestrator.chat_capability import is_general_chat_agent_model_id
    from contextual_orchestrator.model_discovery import discover_all_models, free_discovered_models
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
    )

    registered = register_review_credentials(os.environ)
    auth_token = args.auth_token or get_credential(REVIEW_AUTH_CREDENTIAL_NAME)
    if not auth_token:
        raise SystemExit(
            "review sidecar requires an explicit --auth-token or the "
            f"KV credential {REVIEW_AUTH_CREDENTIAL_NAME!r}"
        )
    if not any(name.startswith(("BYTEZ_", "NVIDIA_", "OPENROUTER_", "OPENAI_")) for name in registered):
        raise SystemExit("review sidecar requires at least one provider credential in the KV")

    try:
        discovered, _ = discover_all_models()
    except Exception as exc:  # pragma: no cover - provider/networking failure is runtime-only
        raise SystemExit(f"review sidecar discovery failed: {exc}") from exc
    free_models = []
    for model in free_discovered_models(discovered) if discovered else []:
        model_id = getattr(model, "model_id", "")
        if not is_general_chat_agent_model_id(model_id) or not _has_text_output(model):
            continue
        free_models.append(model)
    if not free_models:
        raise SystemExit("review sidecar discovered no zero-cost models; orchestrator/free would fail closed")

    rows = _free_report_rows(free_models)
    _write_json(args.discovery_out, {"models": rows})
    zdr_endpoints = _load_zdr_endpoints(args.zdr_endpoints)
    result = build_zdr_prioritized_catalog(
        parse_discovery_report({"models": rows}),
        limit=int(os.environ.get("ORCHESTRATOR_CATALOG_LIMIT", "12")),
        family_cap=int(os.environ.get("ORCHESTRATOR_CATALOG_FAMILY_CAP", "4")),
        zdr_endpoints=zdr_endpoints,
        require_zdr=args.require_zdr,
    )
    _write_json(args.catalog_out, {"agents": result["agents"]})
    _write_json(args.report_out, result["report"])

    agents = load_agents(args.catalog_out)
    client = ModelClient(max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS)
    try:
        agents, preflight_report = _preflight_review_agents(agents, client=client)
    except ReviewPreflightError as exc:
        _write_json(args.preflight_out, exc.report)
        raise SystemExit(f"review sidecar preflight failed: {exc}") from None
    _write_json(args.preflight_out, preflight_report)

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
