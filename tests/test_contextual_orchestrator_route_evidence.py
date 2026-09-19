"""Tests for bounded contextual-orchestrator route attempt telemetry."""

from __future__ import annotations

import json

from scripts.ci.contextual_orchestrator_route_evidence import (
    extract_gateway_route_telemetry,
    format_route_telemetry,
)


def test_extract_gateway_route_telemetry_reads_typed_attempts() -> None:
    """CO#1205 typed attempts[] fields are preserved without raw provider bodies."""
    payload = {
        "error": {
            "detail": {
                "model": "openrouter/meta-llama/llama-3.3-70b-instruct:free",
                "terminal_reason": "eligible_candidates_exhausted",
                "attempts": [
                    {
                        "provider_name": "openrouter",
                        "phase": "connecting",
                        "attempt_number": 1,
                        "provider_status": 429,
                    },
                    {
                        "provider_name": "nvidia_nim",
                        "phase": "streaming",
                        "attempt_number": 2,
                        "provider_status": 502,
                    },
                ],
            }
        }
    }
    telemetry = extract_gateway_route_telemetry(json.dumps(payload))
    assert telemetry["served_model"] == "openrouter/meta-llama/llama-3.3-70b-instruct:free"
    assert telemetry["terminal_reason"] == "eligible_candidates_exhausted"
    assert telemetry["provider_attempt_count"] == 2
    assert telemetry["provider_name"] == "nvidia_nim"
    assert telemetry["upstream_phase"] == "streaming"
    assert telemetry["attempt_number"] == 2
    assert telemetry["upstream_status"] == 502


def test_extract_gateway_route_telemetry_rejects_unsafe_identifiers() -> None:
    """Free-form provider error text must not become public telemetry."""
    payload = {
        "error": {
            "detail": {
                "model": "bad\nmodel",
                "terminal_reason": "x" * 300,
                "attempts": [{"provider_name": "ok", "attempt_number": 999}],
            }
        }
    }
    # Present-but-unsafe model/terminal_reason fail closed for the whole
    # envelope so allowlisted attempt fields cannot launder free-form text.
    assert extract_gateway_route_telemetry(json.dumps(payload)) == {}


def test_format_route_telemetry_is_stable() -> None:
    """Formatted telemetry uses a fixed key order for log correlation."""
    formatted = format_route_telemetry(
        {
            "terminal_reason": "pool_exhausted",
            "provider_attempt_count": 3,
            "served_model": "orchestrator/free",
        }
    )
    assert formatted == (
        "provider_attempt_count=3 terminal_reason=pool_exhausted served_model=orchestrator/free"
    )
