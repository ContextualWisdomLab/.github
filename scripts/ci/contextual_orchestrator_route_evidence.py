"""Consume bounded contextual-orchestrator route attempt telemetry.

Typed ``attempts[]`` and ``terminal_reason`` on gateway error envelopes were
added for ``route_once`` failover in ContextualWisdomLab/contextual-orchestrator#1205
(closes #1016). OpenCode and Noema consumers share this allowlisted parser so
same-model retries preserve provider-outcome evidence without re-emitting raw
provider bodies.
"""

from __future__ import annotations

import json
import re
from typing import Any


SAFE_MODEL_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,199}$")
MAX_HTTP_ERROR_BODY_BYTES = 65536


def safe_model_identifier(value: Any) -> str | None:
    """Return a conservative model or route identifier safe for public logs."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not SAFE_MODEL_IDENTIFIER_RE.fullmatch(candidate):
        return None
    return candidate


def extract_gateway_route_telemetry(raw: str | bytes) -> dict[str, str | int]:
    """Parse allowlisted route evidence from one gateway HTTP error envelope.

    Only ``error.detail`` scalar fields and bounded ``attempts[]`` entries are
    retained. Malformed, oversized, or present-but-unsafe ``model`` /
    ``terminal_reason`` values fail closed to an empty mapping so allowlisted
    attempt fields cannot launder free-form error text.
    """
    if isinstance(raw, bytes):
        if len(raw) > MAX_HTTP_ERROR_BODY_BYTES:
            return {}
        try:
            raw_text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return {}
    else:
        raw_text = raw
    try:
        payload = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    error = payload.get("error")
    if not isinstance(error, dict):
        return {}
    detail = error.get("detail")
    if not isinstance(detail, dict):
        return {}
    raw_model = detail.get("model")
    if raw_model is not None:
        model = safe_model_identifier(raw_model)
        if model is None:
            return {}
    else:
        model = None
    raw_terminal_reason = detail.get("terminal_reason")
    if raw_terminal_reason is not None:
        terminal_reason = safe_model_identifier(raw_terminal_reason)
        if terminal_reason is None:
            return {}
    else:
        terminal_reason = None
    telemetry: dict[str, str | int] = {}
    attempts = detail.get("attempts")
    if model is not None:
        telemetry["served_model"] = model
    if terminal_reason is not None:
        telemetry["terminal_reason"] = terminal_reason
    if isinstance(attempts, list) and attempts and len(attempts) <= 64:
        telemetry["provider_attempt_count"] = len(attempts)
        last_attempt = attempts[-1]
        if isinstance(last_attempt, dict):
            provider_name = safe_model_identifier(last_attempt.get("provider_name"))
            phase = safe_model_identifier(last_attempt.get("phase"))
            attempt_number = last_attempt.get("attempt_number")
            provider_status = last_attempt.get("provider_status")
            if provider_name is not None:
                telemetry["provider_name"] = provider_name
            if phase is not None:
                telemetry["upstream_phase"] = phase
            if type(attempt_number) is int and 1 <= attempt_number <= 64:
                telemetry["attempt_number"] = attempt_number
            if type(provider_status) is int and 100 <= provider_status <= 599:
                telemetry["upstream_status"] = provider_status
    return telemetry


def format_route_telemetry(telemetry: dict[str, str | int]) -> str:
    """Format allowlisted route telemetry for bounded Actions logs."""
    ordered_keys = (
        "provider_attempt_count",
        "provider_name",
        "upstream_phase",
        "attempt_number",
        "upstream_status",
        "terminal_reason",
        "served_model",
    )
    return " ".join(f"{key}={telemetry[key]}" for key in ordered_keys if key in telemetry)
