"""Classify an all-429 review-sidecar preflight as provider capacity (#2148).

The sidecar launcher writes ``strix_runs/contextual-orchestrator-preflight.json``
(contract ``strix-plain-chat-preflight-v2``) before it exits on a failed
preflight. When every probed route was refused with HTTP 429 and none is ready,
the private-target ZDR pool is rate-limited rather than broken, which is the same
``provider_capacity_unavailable`` class ADR-0031 already re-dispatches after a
gateway failure. This module emits the same step outputs as
``two_phase._emit_transport_capacity_outputs`` (via the stdlib-only
``noema_transport_redispatch`` helpers) so the existing bounded
re-dispatch step can consume them. It never changes the job result: the
provisioning step has already failed and review remains required.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - executed as a workflow script
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

# Stdlib-only on purpose: this runs on the runner's bare python3 after the
# sidecar step failed, before the HWP reader step installs defusedxml, so it
# must not import noema_review_gate (whose document import needs it).
from scripts.ci import noema_transport_redispatch as gate  # noqa: E402

PREFLIGHT_CONTRACT = "strix-plain-chat-preflight-v2"
PREFLIGHT_CAPACITY_HTTP_STATUS = 429
PREFLIGHT_CAPACITY_ROUTE_STATUSES = frozenset({"rejected", "deferred"})
MAX_PREFLIGHT_REPORT_BYTES = 256 * 1024


def _exact_int(value: Any) -> int | None:
    """Return ``value`` only when it is a real ``int`` (``bool`` is rejected)."""
    return value if type(value) is int else None


def _stage_retry_after(report: Any) -> list[int] | None:
    """Return one all-429 stage's in-cap ``retry_after_s`` values, or None if not all-429.

    A stage qualifies only when ``ready_count`` is 0, ``probed_count`` is at
    least 1, ``routes`` holds exactly ``probed_count`` rows, and every row is a
    rejected or deferred route whose ``http_status`` is the integer 429.
    """
    if not isinstance(report, dict) or report.get("contract") != PREFLIGHT_CONTRACT:
        return None
    probed = _exact_int(report.get("probed_count"))
    routes = report.get("routes")
    if _exact_int(report.get("ready_count")) != 0 or probed is None or probed < 1:
        return None
    if not isinstance(routes, list) or len(routes) != probed:
        return None
    waits: list[int] = []
    for row in routes:
        if not isinstance(row, dict):
            return None
        if row.get("status") not in PREFLIGHT_CAPACITY_ROUTE_STATUSES:
            return None
        if _exact_int(row.get("http_status")) != PREFLIGHT_CAPACITY_HTTP_STATUS:
            return None
        wait = _exact_int(row.get("retry_after_s"))
        if wait is not None and 1 <= wait <= gate.TRANSPORT_REDISPATCH_RETRY_AFTER_MAX_SECONDS:
            waits.append(wait)
    return waits


def classify_preflight_report(report: Any) -> tuple[int, int | None] | None:
    """Return ``(probed_count, retry_after_seconds)`` for an all-429 report, else None.

    A nested ``primary_attempt`` (a fallback stage also ran) must itself be
    all-429. ``retry_after_seconds`` is the longest provider-stated wait inside
    ADR-0031's existing cap, or None so the deterministic jitter applies.
    """
    waits = _stage_retry_after(report)
    if waits is None:
        return None
    probed = report["probed_count"]
    if "primary_attempt" in report:
        primary_waits = _stage_retry_after(report["primary_attempt"])
        if primary_waits is None:
            return None
        waits.extend(primary_waits)
        probed += report["primary_attempt"]["probed_count"]
    return probed, (max(waits) if waits else None)


def load_preflight_report(path: Path) -> Any:
    """Return the parsed report, or None when it is missing, oversized, or not JSON."""
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_PREFLIGHT_REPORT_BYTES + 1)
        if len(raw) > MAX_PREFLIGHT_REPORT_BYTES:
            return None
        return json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return None


def emit_preflight_capacity_outputs(path: Path, *, expected_head: str) -> dict[str, str]:
    """Write the ADR-0031 transport outputs for one failed sidecar preflight."""
    classified = classify_preflight_report(load_preflight_report(path))
    if classified is None:
        outputs = {"transport_capacity_unavailable": "false", "transport_retry_eligible": "false"}
        gate.append_github_output(outputs)
        return outputs
    probed, retry_after = classified
    retry_attempt = gate.current_transport_retry_attempt()
    delay = gate.transport_redispatch_delay_seconds(
        transport_retry_attempt=retry_attempt,
        head_sha=expected_head,
        retry_after_seconds=retry_after,
    )
    outputs = {
        "transport_capacity_unavailable": "true",
        "transport_retry_eligible": "true" if delay is not None else "false",
        "transport_http_status": str(PREFLIGHT_CAPACITY_HTTP_STATUS),
        "provider_attempt_count": str(probed),
    }
    if delay is not None:
        outputs["transport_retry_delay_seconds"] = str(delay)
        outputs["transport_retry_next_attempt"] = str(retry_attempt + 1)
        print(
            "::notice::Noema sidecar preflight was all-429 (provider capacity unavailable); "
            f"bounded continuation re-dispatch is eligible in {delay}s "
            f"(attempt {retry_attempt + 1}/{gate.MAX_TRANSPORT_REDISPATCH_ATTEMPTS})."
        )
    else:
        print(
            "::error::Noema sidecar preflight was all-429 (provider capacity unavailable); "
            "automatic re-dispatch budget is exhausted. Review remains required."
        )
    gate.append_github_output(outputs)
    return outputs


def main(argv: list[str]) -> int:
    """Classify one preflight report; always exit 0 because the job already failed."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-report", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    args = parser.parse_args(argv)
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        print("::error::--expected-head must be a canonical lowercase 40-character Git SHA.")
        return 0
    emit_preflight_capacity_outputs(args.preflight_report, expected_head=args.expected_head)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
