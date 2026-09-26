"""Summarize the per-candidate trail of the last serving request in a sidecar log.

When every ``orchestrator/free`` candidate fails, the review gate only sees the
gateway's final HTTP status -- the *last* candidate's error. On 2026-09-25 a
Noema run (Actions run 36166447802) reported ``HTTP 429
provider_capacity_unavailable`` after 1041.5 s although six ready NVIDIA routes
had first failed with a disconnect, a 504 and four unusable responses; only the
two deferred OpenRouter routes tried last answered 429. This module reads the
already-sanitized sidecar stderr log and prints one annotation listing every
candidate the last serving request tried, in order, with its outcome and
elapsed time, so the final status is not mistaken for the dominant cause.

It is diagnostic only: it never changes a gate verdict, exit status, or the
transport-retry eligibility the gate derives from the HTTP status.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (?P<event>[a-z_]+) (?P<rest>.*)$"
)
_FIELD_RE = re.compile(r"(?P<key>[a-z_]+)=(?P<value>\S+)")
_AGENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
_ERROR_TYPE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
MAX_LISTED_CANDIDATES = 24


def _parse_line(line: str) -> tuple[datetime, str, dict[str, str]] | None:
    """Return ``(timestamp, event, fields)`` for a sidecar log line, else ``None``."""

    match = _LINE_RE.match(line.strip())
    if match is None:
        return None
    timestamp = datetime.strptime(match["ts"], "%Y-%m-%d %H:%M:%S,%f")
    fields = {m["key"]: m["value"] for m in _FIELD_RE.finditer(match["rest"])}
    return timestamp, match["event"], fields


def _failure_outcome(fields: dict[str, str]) -> str:
    """Classify one ``provider_attempt_failed`` line into a bounded outcome label."""

    status = fields.get("provider_status", "")
    if status.isdigit():
        return f"http_{status}"
    error_type = fields.get("error_type", "")
    if not _ERROR_TYPE_RE.match(error_type):
        return "transport_error"
    lowered = error_type.lower()
    if "timeout" in lowered:
        return "timeout"
    if "disconnect" in lowered or "reset" in lowered:
        return "disconnect"
    return lowered


def summarize(lines: list[str]) -> tuple[str, list[dict[str, object]]] | None:
    """Return the last serving request id and its ordered candidate trail.

    Preflight probes carry ``request_id=-`` and are ignored; a serving request
    carries a 32-hex request id. ``circuit_failure`` lines carry no request id
    and are attributed to the agent's most recent attempt. A candidate whose
    circuit tripped without a transport failure is labelled
    ``invalid_response``; one with no recorded failure keeps
    ``no_failure_recorded``.
    """

    trails: dict[str, list[dict[str, object]]] = {}
    entries: dict[tuple[str, str], dict[str, object]] = {}
    last_request_for_agent: dict[str, str] = {}
    last_request: str | None = None
    for line in lines:
        parsed = _parse_line(line)
        if parsed is None:
            continue
        timestamp, event, fields = parsed
        agent = fields.get("agent_id", "")
        if not _AGENT_RE.match(agent):
            continue
        request_id = fields.get("request_id", "")
        if not _REQUEST_ID_RE.match(request_id):
            request_id = last_request_for_agent.get(agent, "") if event == "circuit_failure" else ""
        if not request_id:
            continue
        key = (request_id, agent)
        entry = entries.get(key)
        if event == "provider_attempt":
            last_request_for_agent[agent] = request_id
            last_request = request_id
            if entry is None:
                entry = {"agent_id": agent, "started": timestamp, "ended": None, "outcome": None}
                entries[key] = entry
                trails.setdefault(request_id, []).append(entry)
            continue
        if entry is None:
            continue
        if event == "provider_attempt_failed":
            entry["outcome"] = _failure_outcome(fields)
            entry["ended"] = timestamp
        elif event == "circuit_failure":
            if entry["outcome"] is None:
                entry["outcome"] = "invalid_response"
            entry["ended"] = timestamp
    if last_request is None:
        return None
    return last_request, trails[last_request]


def format_annotation(request_id: str, trail: list[dict[str, object]]) -> str:
    """Render one GitHub Actions ``::notice`` line for a candidate trail."""

    first_start = trail[0]["started"]
    steps: list[str] = []
    counts: Counter[str] = Counter()
    last_end = first_start
    for index, entry in enumerate(trail, start=1):
        outcome = str(entry["outcome"] or "no_failure_recorded")
        counts[outcome] += 1
        ended = entry["ended"] or entry["started"]
        last_end = max(last_end, ended)  # type: ignore[type-var]
        if index <= MAX_LISTED_CANDIDATES:
            elapsed = (ended - entry["started"]).total_seconds()  # type: ignore[operator]
            steps.append(f"{index}) {entry['agent_id']} {outcome} after {elapsed:.1f}s")
    if len(trail) > MAX_LISTED_CANDIDATES:
        steps.append(f"... {len(trail) - MAX_LISTED_CANDIDATES} more")
    total = (last_end - first_start).total_seconds()  # type: ignore[operator]
    tally = ", ".join(f"{name}={count}" for name, count in sorted(counts.items()))
    return (
        "::notice title=SIDECAR_CANDIDATE_TRAIL::"
        f"request {request_id[:8]} tried {len(trail)} candidate(s) over {total:.1f}s: "
        + "; ".join(steps)
        + f". Outcomes: {tally}. The gateway's final status reflects only the last candidate."
    )


def main(argv: list[str]) -> int:
    """Print the candidate-trail annotation for the sidecar log at ``argv[1]``.

    Always returns 0: a missing or unreadable log, or one with no serving
    request, prints nothing because this summary must never fail a job.
    """

    if len(argv) != 2:
        print("usage: sidecar_route_trail.py <sidecar-stderr-log>", file=sys.stderr)
        return 0
    path = Path(argv[1])
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    result = summarize(lines)
    if result is not None:
        print(format_annotation(*result))
    return 0


if __name__ == "__main__":  # pragma: no cover - thin CLI wrapper
    raise SystemExit(main(sys.argv))
