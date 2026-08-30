#!/usr/bin/env python3
"""Reduce contextual-orchestrator sidecar streams to bounded safe diagnostics."""

from __future__ import annotations

import re
import sys


_REQUEST_FAILED = re.compile(
    r"request_failed status=(?P<status>[1-5][0-9]{2}) "
    r"code=(?P<code>[A-Za-z0-9_.-]{1,64})"
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


def sanitize_line(line: str) -> str | None:
    """Return one allowlisted diagnostic summary or ``None`` for raw content."""
    stripped = line.strip()
    request_failed = _REQUEST_FAILED.search(stripped)
    if request_failed is not None:
        return (
            f"request_failed status={request_failed.group('status')} "
            f"code={request_failed.group('code')}"
        )
    if stripped == "client_disconnected":
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
