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


def main(argv: list[str] | None = None) -> int:
    """Bootstrap the KV, discover free models, build the ZDR catalog, and serve.

    Args:
        argv: CLI arguments (``--host``, ``--port``, ``--auth-token``,
            ``--catalog-out``, ``--report-out``, ``--discovery-out``,
            ``--zdr-endpoints``).

    Returns:
        0 when the server exits cleanly; 1 on any configuration error.

    Raises:
        SystemExit: If the vendored library is missing, no provider credential
            is in the KV, no free model was discovered, or no auth token is
            available — the sidecar must fail closed rather than boot a mock or
            unaudited pool.
    """
    parser = argparse.ArgumentParser(description="Serve the contextual-orchestrator review sidecar.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--auth-token", default="", help="Explicit bearer token; else resolve from the KV")
    parser.add_argument("--discovery-out", required=True, help="Path to write the free-only discovery report JSON")
    parser.add_argument("--catalog-out", required=True, help="Path to write the agents catalog JSON")
    parser.add_argument("--report-out", required=True, help="Path to write the policy evidence JSON")
    parser.add_argument("--zdr-endpoints", default=None, help="Optional OpenRouter /api/v1/endpoints/zdr JSON path")
    args = parser.parse_args(argv)

    from contextual_orchestrator.credentials import get_credential
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
    free_models = free_discovered_models(discovered) if discovered else []
    if not free_models:
        raise SystemExit("review sidecar discovered no zero-cost models; orchestrator/free would fail closed")

    rows = _free_report_rows(free_models)
    Path(args.discovery_out).write_text(
        json.dumps({"models": rows}, indent=2) + "\n", encoding="utf-8"
    )
    zdr_endpoints = _load_zdr_endpoints(args.zdr_endpoints)
    result = build_zdr_prioritized_catalog(
        parse_discovery_report({"models": rows}),
        limit=int(os.environ.get("ORCHESTRATOR_CATALOG_LIMIT", "12")),
        family_cap=int(os.environ.get("ORCHESTRATOR_CATALOG_FAMILY_CAP", "4")),
        zdr_endpoints=zdr_endpoints,
    )
    Path(args.catalog_out).write_text(
        json.dumps(result["agents"], indent=2) + "\n", encoding="utf-8"
    )
    Path(args.report_out).write_text(
        json.dumps(result["report"], indent=2) + "\n", encoding="utf-8"
    )

    agents = load_agents(args.catalog_out)
    orchestrator = TaskOrchestrator(agents, client=ModelClient(max_output_tokens=32768))
    serve(
        orchestrator,
        host=args.host,
        port=args.port,
        security=SecurityConfig(auth_token=auth_token),
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())