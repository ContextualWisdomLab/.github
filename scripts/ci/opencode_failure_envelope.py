#!/usr/bin/env python3
"""Emit bounded, redaction-safe metadata for one failed OpenCode invocation."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


MAX_FAILURE_FILE_BYTES = 65_536
MAX_GATEWAY_BODY_BYTES = 32_768
SAFE_VALUE_RE = re.compile(r"[A-Za-z0-9_./:-]{1,128}")


def _read_bounded(path: Path) -> tuple[bytes, int]:
    """Read a bounded prefix while retaining the file's non-secret byte count."""
    try:
        byte_count = path.stat().st_size
        with path.open("rb") as stream:
            return stream.read(MAX_FAILURE_FILE_BYTES + 1), byte_count
    except OSError:
        return b"", 0


def _safe_value(value: Any) -> str | None:
    """Return one conservative public-log token or no value."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    return candidate if SAFE_VALUE_RE.fullmatch(candidate) else None


def _safe_exception(value: Any) -> str | None:
    """Return a bounded Python-style exception identifier or no value."""
    if not isinstance(value, str) or len(value) > 64 or not value.isidentifier():
        return None
    return value


def _safe_http_status(value: Any) -> int | None:
    """Return a valid HTTP status while excluding booleans and free text."""
    if type(value) is int and 100 <= value <= 599:
        return value
    if isinstance(value, str) and len(value) == 3 and value.isascii() and value.isdigit():
        status = int(value)
        return status if 100 <= status <= 599 else None
    return None


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
        except (json.JSONDecodeError, TypeError, ValueError):
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
            malformed = not isinstance(payload, dict)
        except (json.JSONDecodeError, TypeError, ValueError):
            return {}, True
    else:
        return {}, True
    if not isinstance(payload, dict):
        return {}, malformed
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
) -> str:
    """Normalize one failure class without returning provider-controlled text."""
    searchable = (raw_json + b"\n" + raw_stderr).lower()
    normalized_reason = (reason or "").lower()
    if status == 413 or b"request_too_large" in searchable or b"request body too large" in searchable:
        return "request-too-large"
    if b"contextoverflowerror" in searchable or b"tokens_limit_reached" in searchable or b"context window" in searchable:
        return "context-window"
    if status == 402 or b"insufficient credits" in searchable or b"payment required" in searchable:
        return "credit-exhausted"
    if b"budget limit" in searchable or b"insufficient_quota" in searchable or b"quota exceeded" in searchable:
        return "quota-or-budget"
    if normalized_reason in {"eligible_candidates_exhausted", "no_eligible_route", "model_pool_exhausted"}:
        return "model-pool-exhausted"
    if b"model_not_found" in searchable or b"model not found" in searchable or b"no endpoints" in searchable:
        return "model-unavailable"
    if status == 429 or b"rate_limit" in searchable or b"rate limit" in searchable or b"too many requests" in searchable:
        return "rate-limit"
    if status in {401, 403} or b"permission denied" in searchable or b"authentication" in searchable or b"authorization" in searchable:
        return "authentication-or-permission"
    if b"timed out" in searchable or b"timeout" in searchable:
        return "timeout"
    if status is not None and 500 <= status <= 599:
        return "provider-5xx"
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
    reason = next(
        (
            safe
            for safe in (
                _safe_value(detail.get("terminal_reason")),
                _safe_value(detail.get("stop_reason")),
                _safe_value(detail.get("error_code")),
                _safe_value(data.get("code")),
            )
            if safe is not None
        ),
        None,
    )
    status = next(
        (
            safe
            for safe in (
                _safe_http_status(data.get("statusCode")),
                _safe_http_status(data.get("status_code")),
                _safe_http_status(last_attempt.get("provider_status")),
            )
            if safe is not None
        ),
        None,
    )
    failure_class = _failure_class(
        raw_json,
        raw_stderr,
        status=status,
        reason=reason,
        malformed_body=malformed_body,
        has_event=event is not None,
    )
    normalized_reason = reason or failure_class.replace("-", "_")
    fields = {
        "class": failure_class,
        "json-bytes": str(json_bytes),
        "stderr-bytes": str(stderr_bytes),
        "phase": _safe_value(last_attempt.get("phase")) or _safe_value(detail.get("phase")) or "unknown",
        "reason": normalized_reason,
        "provider": _safe_value(last_attempt.get("provider_name")) or _safe_value(last_attempt.get("provider")) or "unknown",
        "http-status": str(status) if status is not None else "unknown",
        "exception": _safe_exception(error.get("name")) or "unknown",
        "duration-seconds": str(max(0, duration_seconds)),
        "served-model": _safe_value(detail.get("model")) or "unknown",
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
