#!/usr/bin/env python3
"""Emit bounded, redaction-safe metadata for one failed OpenCode invocation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


MAX_FAILURE_FILE_BYTES = 16_384
MAX_GATEWAY_BODY_BYTES = 32_768
MAX_JSON_DEPTH = 64
SAFE_FAILURE_PHASES = frozenset(
    {
        "admission",
        "authentication",
        "connecting",
        "queue_admission",
        "request_admission",
        "response_error",
        "route_selection",
        "streaming",
    }
)
REASON_FAILURE_CLASSES = {
    "request_too_large": "request-too-large",
    "payload_too_large": "request-too-large",
    "context_overflow": "context-window",
    "context_window_exceeded": "context-window",
    "tokens_limit_reached": "context-window",
    "insufficient_credits": "credit-exhausted",
    "payment_required": "credit-exhausted",
    "budget_limit": "quota-or-budget",
    "insufficient_quota": "quota-or-budget",
    "quota_exceeded": "quota-or-budget",
    "eligible_candidates_exhausted": "model-pool-exhausted",
    "no_eligible_route": "model-pool-exhausted",
    "model_pool_exhausted": "model-pool-exhausted",
    "model_not_found": "model-unavailable",
    "no_endpoints": "model-unavailable",
    "rate_limit": "rate-limit",
    "rate_limited": "rate-limit",
    "too_many_requests": "rate-limit",
    "queue_capacity": "rate-limit",
    "permission_denied": "authentication-or-permission",
    "authentication_failed": "authentication-or-permission",
    "authorization_failed": "authentication-or-permission",
    "timeout": "timeout",
    "timed_out": "timeout",
    "provider_timeout": "timeout",
    "provider_unavailable": "provider-5xx",
    "upstream_error": "provider-5xx",
}


def _read_bounded(path: Path) -> tuple[bytes, int]:
    """Read a bounded final-line tail while retaining the non-secret byte count."""
    try:
        byte_count = path.stat().st_size
        with path.open("rb") as stream:
            truncated = byte_count > MAX_FAILURE_FILE_BYTES
            preceding_byte = b""
            if truncated:
                stream.seek(-MAX_FAILURE_FILE_BYTES - 1, 2)
                preceding_byte = stream.read(1)
            raw = stream.read(MAX_FAILURE_FILE_BYTES)
        if truncated and preceding_byte != b"\n":
            _, separator, raw = raw.partition(b"\n")
            if not separator:
                raw = b""
        return raw, byte_count
    except OSError:
        return b"", 0


def _safe_enum(value: Any, allowed_values: frozenset[str] | dict[str, str]) -> str | None:
    """Return an exact allowlisted receipt token or no value."""
    return value if isinstance(value, str) and value in allowed_values else None


def _safe_http_status(value: Any) -> int | None:
    """Return a valid HTTP status while excluding booleans and free text."""
    if type(value) is int and 100 <= value <= 599:
        return value
    if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isdigit():
        status = int(value)
        return status if 100 <= status <= 599 else None
    return None


def _consistent_authority(values: tuple[Any | None, ...]) -> tuple[Any | None, bool]:
    """Return one exact authority value, or flag conflicting validated values."""
    accepted = tuple(value for value in values if value is not None)
    if not accepted:
        return None, False
    return accepted[0], any(value != accepted[0] for value in accepted[1:])


def _status_failure_class(status: int | None) -> str | None:
    """Map one validated HTTP status to its conservative public class."""
    if status == 413:
        return "request-too-large"
    if status == 402:
        return "credit-exhausted"
    if status == 429:
        return "rate-limit"
    if status in {401, 403}:
        return "authentication-or-permission"
    if status is not None and 500 <= status <= 599:
        return "provider-5xx"
    return "provider-error" if status is not None else None


def _is_within_json_depth(value: Any) -> bool:
    """Return whether a decoded provider value stays within the depth invariant."""
    pending = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            return False
        if isinstance(current, dict):
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            pending.extend((item, depth + 1) for item in current)
    return True


def _last_error_event(raw: bytes) -> dict[str, Any] | None:
    """Return the last bounded OpenCode JSON-lines error event."""
    if len(raw) > MAX_FAILURE_FILE_BYTES:
        return None
    last: dict[str, Any] | None = None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            continue
        if not _is_within_json_depth(event):
            continue
        if isinstance(event, dict) and event.get("type") == "error":
            last = event
    return last


def _gateway_detail(data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Extract the canonical gateway error detail and flag malformed bodies."""
    body_value = next(
        (data.get(key) for key in ("responseBody", "response_body", "body") if key in data),
        None,
    )
    if body_value is None:
        payload: Any = data
        malformed = False
    elif isinstance(body_value, dict):
        payload = body_value
        malformed = False
    elif isinstance(body_value, str):
        try:
            body_bytes = body_value.encode("utf-8")
        except UnicodeEncodeError:
            return {}, True
        if len(body_bytes) > MAX_GATEWAY_BODY_BYTES:
            return {}, True
        try:
            payload = json.loads(body_value)
            if not isinstance(payload, dict) or not _is_within_json_depth(payload):
                return {}, True
            malformed = False
        except (json.JSONDecodeError, RecursionError, TypeError, ValueError):
            return {}, True
    else:
        return {}, True
    error = payload.get("error")
    if isinstance(error, dict) and isinstance(error.get("detail"), dict):
        return error["detail"], malformed
    detail = payload.get("error_detail")
    if isinstance(detail, dict):
        return detail, malformed
    direct = payload.get("detail")
    return (direct, malformed) if isinstance(direct, dict) else ({}, malformed)


def _failure_class(
    raw_json: bytes,
    raw_stderr: bytes,
    *,
    status: int | None,
    reason: str | None,
    malformed_body: bool,
    has_event: bool,
    authority_conflict: bool = False,
) -> str:
    """Normalize one failure class from validated structured receipt fields."""
    if authority_conflict:
        return "provider-error"
    status_class = _status_failure_class(status)
    reason_class = REASON_FAILURE_CLASSES.get(reason or "")
    if status_class is not None and reason_class is not None and status_class != reason_class:
        return "provider-error"
    if reason_class is not None:
        return reason_class
    if status_class is not None:
        return status_class
    if malformed_body or (raw_json and not has_event):
        return "malformed-response"
    if raw_json or raw_stderr:
        return "provider-error"
    return "no-provider-detail"


def format_failure_metadata(
    json_path: Path, stderr_path: Path, duration_seconds: int
) -> str:
    """Format one stable diagnostic line from bounded OpenCode failure artifacts."""
    raw_json, json_bytes = _read_bounded(json_path)
    raw_stderr, stderr_bytes = _read_bounded(stderr_path)
    event = _last_error_event(raw_json)
    error = event.get("error") if isinstance(event, dict) else None
    error = error if isinstance(error, dict) else {}
    data = error.get("data")
    data = data if isinstance(data, dict) else {}
    detail, malformed_body = _gateway_detail(data)
    attempts = detail.get("attempts")
    last_attempt = (
        attempts[-1]
        if isinstance(attempts, list)
        and attempts
        and len(attempts) <= 64
        and isinstance(attempts[-1], dict)
        else {}
    )
    reason, reason_conflict = _consistent_authority(
        (
            _safe_enum(detail.get("terminal_reason"), REASON_FAILURE_CLASSES),
            _safe_enum(detail.get("stop_reason"), REASON_FAILURE_CLASSES),
            _safe_enum(detail.get("error_code"), REASON_FAILURE_CLASSES),
            _safe_enum(data.get("code"), REASON_FAILURE_CLASSES),
        )
    )
    status, status_conflict = _consistent_authority(
        (
            _safe_http_status(data.get("statusCode")),
            _safe_http_status(data.get("status_code")),
            _safe_http_status(last_attempt.get("provider_status")),
        )
    )
    status_class = _status_failure_class(status)
    reason_class = REASON_FAILURE_CLASSES.get(reason or "")
    cross_conflict = (
        status_class is not None
        and reason_class is not None
        and status_class != reason_class
    )
    authority_conflict = reason_conflict or status_conflict or cross_conflict
    failure_class = _failure_class(
        raw_json,
        raw_stderr,
        status=status,
        reason=reason,
        malformed_body=malformed_body,
        has_event=event is not None,
        authority_conflict=authority_conflict,
    )
    normalized_reason = (
        "unknown"
        if authority_conflict
        else reason or failure_class.replace("-", "_")
    )
    fields = {
        "class": failure_class,
        "json-bytes": str(json_bytes),
        "stderr-bytes": str(stderr_bytes),
        "phase": _safe_enum(last_attempt.get("phase"), SAFE_FAILURE_PHASES)
        or _safe_enum(detail.get("phase"), SAFE_FAILURE_PHASES)
        or "unknown",
        "reason": normalized_reason,
        "provider": "unknown",
        "http-status": (
            str(status) if status is not None and not authority_conflict else "unknown"
        ),
        "exception": "unknown",
        "duration-seconds": str(max(0, duration_seconds)),
        "served-model": "unknown",
    }
    rendered = " ".join(f"{key}={value}" for key, value in fields.items())
    return f"OpenCode provider failure metadata: {rendered}; provider-controlled content suppressed."


def main(argv: list[str] | None = None) -> int:
    """Print one redaction-safe failure line for the shell runner."""
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 3 or not arguments[2].isascii() or not arguments[2].isdigit():
        print("usage: opencode_failure_envelope.py JSON STDERR DURATION_SECONDS", file=sys.stderr)
        return 2
    print(format_failure_metadata(Path(arguments[0]), Path(arguments[1]), int(arguments[2])))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the shell contract
    raise SystemExit(main())
