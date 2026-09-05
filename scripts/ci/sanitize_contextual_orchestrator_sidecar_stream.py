#!/usr/bin/env python3
"""Reduce contextual-orchestrator sidecar streams to bounded safe diagnostics."""

from __future__ import annotations

import re
import sys


_REQUEST_FAILED = re.compile(
    r"request_failed status=(?P<status>[1-5][0-9]{2}) "
    r"code=(?P<code>[A-Za-z0-9_.-]{1,64})"
)
_PROVIDER_DISCOVERY_FAILED = re.compile(
    r"provider_discovery_failed provider=(?P<provider>[a-z][a-z0-9_]{0,63}) "
    r"code=(?P<code>[A-Za-z0-9_.-]{1,64})"
)
_PREFLIGHT_ROUTE_REJECTED = re.compile(
    r"preflight_route_rejected provider=(?P<provider>[a-z][a-z0-9_]{0,63}) "
    r"error_type=(?P<error_type>[A-Za-z_][A-Za-z0-9_]{0,63})"
    r"(?: http_status=(?P<http_status>[1-5][0-9]{2}))?"
)
_LOG_PREFIX = re.compile(
    r"^(?:(?P<asctime>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) )?"
    r"(?:DEBUG|INFO|WARNING|ERROR)[: ][A-Za-z0-9_.]+[: ]"
)
_AGENT_ID = r"[a-z][a-z0-9_]*"
_MODEL_ID = r"[A-Za-z0-9_./:-]+"
_ERROR_TYPE = r"[A-Za-z_][A-Za-z0-9_.]*"
_NUMBER = r"\d+(?:\.\d+)?"
# contextual_orchestrator/orchestrator.py templates at the vendored pin. Every
# field is a bounded identifier or number; ``error_message`` is free text and is
# deliberately excluded from the match so it can never be re-emitted.
_ORCHESTRATOR_EVENTS = tuple(
    re.compile(pattern)
    for pattern in (
        rf"^provider_attempt agent_id={_AGENT_ID} model={_MODEL_ID} attempt=\d+/\d+$",
        rf"^provider_attempt_failed agent_id={_AGENT_ID} model={_MODEL_ID} attempt=\d+ "
        rf"error_type={_ERROR_TYPE} transient=(?:True|False)(?= error_message=)",
        rf"^provider_backoff agent_id={_AGENT_ID} attempt=\d+ delay_seconds={_NUMBER}$",
        rf"^provider_exhausted agent_id={_AGENT_ID} model={_MODEL_ID} attempts=\d+ "
        rf"final_error_type={_ERROR_TYPE}$",
        rf"^provider_rejected_permanent agent_id={_AGENT_ID} model={_MODEL_ID} attempts=\d+ "
        rf"final_error_type={_ERROR_TYPE}$",
        rf"^provider_no_retry_budget agent_id={_AGENT_ID} model={_MODEL_ID} attempts=\d+ "
        rf"final_error_type={_ERROR_TYPE} transient=(?:True|False)$",
        rf"^circuit_failure agent_id={_AGENT_ID} failures=\d+ threshold=\d+$",
        rf"^circuit_opened agent_id={_AGENT_ID} failures=\d+ threshold=\d+ reset_seconds={_NUMBER}$",
        rf"^circuit_reset agent_id={_AGENT_ID}$",
        rf"^circuit_cleared agent_id={_AGENT_ID}$",
    )
)
_PREFIX_SUMMARIES = (
    ("review sidecar preflight failed:", "review sidecar preflight failed"),
    ("review sidecar discovery failed:", "review sidecar discovery failed"),
    (
        # Matches contextual_orchestrator_review_launcher.py's actual
        # SystemExit text ("no eligible models", not "no zero-cost models" --
        # that stale prefix never matched the launcher's real message, so
        # this fail-closed diagnostic was silently dropped to
        # omitted_unstructured_lines instead of reaching CI operators).
        "review sidecar discovered no eligible models;",
        "review sidecar discovered no eligible models",
    ),
    (
        "review sidecar requires an explicit --auth-token or the KV credential",
        "review sidecar auth token unavailable",
    ),
    (
        "review sidecar requires at least one provider credential in the KV",
        "review sidecar requires at least one provider credential in the KV",
    ),
)


def _sanitize_orchestrator_event(stripped: str) -> str | None:
    """Return an orchestrator route or circuit event reduced to its bounded fields.

    Accepts the bare message, Python's default ``LEVEL:name:message`` prefix, and
    the sidecar formatter's ``asctime LEVEL name message`` prefix; the timestamp
    is kept (digits and punctuation only) so per-route durations can be read as
    differences. ``provider_attempt_failed`` is cut before ``error_message=``,
    which carries upstream text.
    """
    prefix = _LOG_PREFIX.match(stripped)
    message = stripped[prefix.end():] if prefix is not None else stripped
    for pattern in _ORCHESTRATOR_EVENTS:
        match = pattern.match(message)
        if match is None:
            continue
        summary = match.group(0)
        if message.startswith("provider_attempt_failed "):
            summary += " error_message=<omitted>"
        asctime = prefix.group("asctime") if prefix is not None else None
        return f"{asctime} {summary}" if asctime else summary
    return None


def sanitize_line(line: str) -> str | None:
    """Return one allowlisted diagnostic summary or ``None`` for raw content."""
    stripped = line.strip()
    request_failed = _REQUEST_FAILED.search(stripped)
    if request_failed is not None:
        return (
            f"request_failed status={request_failed.group('status')} "
            f"code={request_failed.group('code')}"
        )
    provider_discovery_failed = _PROVIDER_DISCOVERY_FAILED.search(stripped)
    if provider_discovery_failed is not None:
        return (
            f"provider_discovery_failed provider={provider_discovery_failed.group('provider')} "
            f"code={provider_discovery_failed.group('code')}"
        )
    preflight_route_rejected = _PREFLIGHT_ROUTE_REJECTED.search(stripped)
    if preflight_route_rejected is not None:
        summary = (
            f"preflight_route_rejected provider={preflight_route_rejected.group('provider')} "
            f"error_type={preflight_route_rejected.group('error_type')}"
        )
        http_status = preflight_route_rejected.group("http_status")
        if http_status is not None:
            summary += f" http_status={http_status}"
        return summary
    orchestrator_event = _sanitize_orchestrator_event(stripped)
    if orchestrator_event is not None:
        return orchestrator_event
    if stripped in ("client_disconnected", "discovery_diagnostics_complete"):
        return stripped
    for prefix, summary in _PREFIX_SUMMARIES:
        if stripped.startswith(prefix):
            return summary
    return None


def main() -> int:
    """Stream sanitized summaries to stdout without retaining raw provider text."""
    omitted = 0
    unexpected_exception_reported = False
    for line in sys.stdin:
        if line.lstrip().startswith("Traceback"):
            if not unexpected_exception_reported:
                print("sidecar emitted an unexpected exception", flush=True)
                unexpected_exception_reported = True
            continue
        sanitized = sanitize_line(line)
        if sanitized is None:
            omitted += 1
            continue
        print(sanitized, flush=True)
    if omitted:
        print(f"omitted_unstructured_lines={omitted}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through ``main`` tests
    raise SystemExit(main())
