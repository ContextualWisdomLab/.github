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


def test_extract_gateway_route_telemetry_fail_closed_cases() -> None:
    """Malformed or oversized envelopes never emit partial unsafe telemetry."""
    from scripts.ci.contextual_orchestrator_route_evidence import (
        MAX_HTTP_ERROR_BODY_BYTES,
        safe_model_identifier,
    )

    assert safe_model_identifier(42) is None
    assert extract_gateway_route_telemetry(b"x" * (MAX_HTTP_ERROR_BODY_BYTES + 1)) == {}
    assert extract_gateway_route_telemetry(b"\xff\xfe") == {}
    assert extract_gateway_route_telemetry("not-json") == {}
    assert extract_gateway_route_telemetry("[]") == {}
    assert extract_gateway_route_telemetry(json.dumps({"error": "x"})) == {}
    assert extract_gateway_route_telemetry(json.dumps({"error": {"detail": "x"}})) == {}
    assert (
        extract_gateway_route_telemetry(
            json.dumps({"error": {"detail": {"model": "bad\nmodel", "attempts": []}}})
        )
        == {}
    )
    assert (
        extract_gateway_route_telemetry(
            json.dumps(
                {
                    "error": {
                        "detail": {
                            "terminal_reason": "x" * 300,
                            "attempts": [{"provider_name": "ok"}],
                        }
                    }
                }
            )
        )
        == {}
    )


def test_extract_gateway_route_telemetry_ignores_empty_or_oversized_attempt_lists() -> None:
    """Empty or oversized attempt lists do not emit attempt telemetry."""
    assert (
        extract_gateway_route_telemetry(json.dumps({"error": {"detail": {"attempts": []}}}))
        == {}
    )
    attempts = [{"provider_name": "openrouter", "attempt_number": 1}] * 65
    assert (
        extract_gateway_route_telemetry(json.dumps({"error": {"detail": {"attempts": attempts}}}))
        == {}
    )
    assert (
        extract_gateway_route_telemetry(json.dumps({"error": {"detail": {"attempts": "bad"}}}))
        == {}
    )


def test_extract_gateway_route_telemetry_ignores_non_object_attempt_rows() -> None:
    """Attempt rows must be objects before any subfield is read."""
    payload = {"error": {"detail": {"attempts": ["not-an-object"]}}}
    assert extract_gateway_route_telemetry(json.dumps(payload)) == {
        "provider_attempt_count": 1
    }


def test_extract_gateway_route_telemetry_ignores_invalid_attempt_fields() -> None:
    """Invalid attempt subfields are omitted without rejecting the envelope."""
    payload = {
        "error": {
            "detail": {
                "model": "orchestrator/free",
                "attempts": [
                    {
                        "provider_name": "bad name",
                        "phase": "bad phase",
                        "attempt_number": 999,
                        "provider_status": 999,
                    }
                ],
            }
        }
    }
    telemetry = extract_gateway_route_telemetry(json.dumps(payload))
    assert telemetry == {"served_model": "orchestrator/free", "provider_attempt_count": 1}


def test_extract_gateway_route_telemetry_optional_attempt_fields() -> None:
    """Allowlisted attempt fields are optional and independently validated."""
    payload = {
        "error": {
            "detail": {
                "attempts": [
                    {
                        "provider_name": "openrouter",
                        "phase": "streaming",
                        "attempt_number": 2,
                        "provider_status": 503,
                    }
                ]
            }
        }
    }
    telemetry = extract_gateway_route_telemetry(json.dumps(payload))
    assert telemetry["provider_attempt_count"] == 1
    assert telemetry["provider_name"] == "openrouter"
    assert telemetry["upstream_phase"] == "streaming"
    assert telemetry["attempt_number"] == 2
    assert telemetry["upstream_status"] == 503
