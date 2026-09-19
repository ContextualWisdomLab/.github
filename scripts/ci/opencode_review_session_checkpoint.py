#!/usr/bin/env python3
"""Host-managed OpenCode same-model session checkpoints and continuations.

The trusted review host records partial attempt state and injects bounded
resume context on same-model retries. Checkpoints never grant approval
authority and never replay provider-controlled bodies into prompts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:  # pragma: no cover - bootstrap only on direct script execution
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.ci.contextual_orchestrator_route_evidence import (  # noqa: E402
    extract_gateway_route_telemetry,
    format_route_telemetry,
)


CHECKPOINT_SCHEMA = 1
CONTROL_SENTINEL = "opencode-review-control-v1"
REQUIRED_OUTPUT_MARKERS = (
    CONTROL_SENTINEL,
    "adversarial_validation",
    '"result"',
    "Developer experience:",
    "User experience:",
)
TERMINATION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("provider-fatal", re.compile(r"contextoverflowerror|tokens_limit_reached|model_not_found|no endpoints", re.I)),
    ("provider-timeout", re.compile(r"timed?\ ?out|timeout", re.I)),
    ("provider-rate-limit", re.compile(r"rate.?limit|too many requests|\b429\b", re.I)),
    ("provider-error", re.compile(r'"type"\s*:\s*"error"', re.I)),
    ("export-empty", re.compile(r"assistant-empty-export", re.I)),
    ("invalid-control", re.compile(r"invalid-control-output", re.I)),
    ("sessionless", re.compile(r"sessionless-json", re.I)),
    ("nonzero-exit", re.compile(r"exit", re.I)),
)
MAX_PARTIAL_DIGEST_CHARS = 64
MAX_CONTINUATION_BYTES = 8192
DEFAULT_CONTINUATION_BUDGET = 2


def _read_bounded_text(path: Path, max_bytes: int) -> str:
    """Read at most ``max_bytes`` from a file as UTF-8 replacement text."""
    if not path.is_file():
        return ""
    try:
        with path.open("rb") as bounded_stream:
            data = bounded_stream.read(max_bytes)
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")


def classify_termination(
    *,
    json_path: Path,
    export_path: Path,
    exit_code: int,
    stderr_path: Path | None = None,
    log_hint: str = "",
) -> str:
    """Return a bounded termination reason for one OpenCode attempt."""
    combined = "\n".join(
        part
        for part in (
            _read_bounded_text(json_path, 65536),
            _read_bounded_text(export_path, 65536),
            _read_bounded_text(stderr_path, 65536) if stderr_path else "",
            log_hint,
        )
        if part
    )
    for label, pattern in TERMINATION_PATTERNS:
        if pattern.search(combined):
            return label
    if exit_code != 0:
        return "nonzero-exit"
    if not summarize_partial_assistant(export_path).get("assistant_text_present"):
        return "export-empty"
    return "incomplete-control"


def summarize_partial_assistant(export_path: Path) -> dict[str, str | int | bool]:
    """Return bounded metadata about partial assistant output, never raw text."""
    if not export_path.is_file():
        return {
            "assistant_text_present": False,
            "assistant_line_count": 0,
            "assistant_sha256": "",
            "has_control_sentinel": False,
        }
    try:
        payload = json.loads(export_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {
            "assistant_text_present": False,
            "assistant_line_count": 0,
            "assistant_sha256": "",
            "has_control_sentinel": False,
        }
    texts: list[str] = []
    if isinstance(payload, dict):
        messages = payload.get("messages")
        if isinstance(messages, list):
            for message in messages:
                if not isinstance(message, dict):
                    continue
                info = message.get("info")
                if not isinstance(info, dict) or info.get("role") != "assistant":
                    continue
                parts = message.get("parts")
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text")
                        if isinstance(text, str) and text.strip():
                            texts.append(text)
    joined = "\n".join(texts)
    digest = hashlib.sha256(joined.encode("utf-8")).hexdigest() if joined else ""
    return {
        "assistant_text_present": bool(joined.strip()),
        "assistant_line_count": len(joined.splitlines()) if joined else 0,
        "assistant_sha256": digest[:MAX_PARTIAL_DIGEST_CHARS],
        "has_control_sentinel": CONTROL_SENTINEL in joined,
    }


def missing_required_outputs(partial_text: str) -> list[str]:
    """Return required review output markers absent from partial assistant text."""
    missing: list[str] = []
    for marker in REQUIRED_OUTPUT_MARKERS:
        if marker not in partial_text:
            missing.append(marker)
    return missing


def _load_checkpoint(path: Path) -> dict[str, Any]:
    """Load an existing checkpoint or return an empty document."""
    if not path.is_file():
        return {"schema": CHECKPOINT_SCHEMA, "attempts": []}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"schema": CHECKPOINT_SCHEMA, "attempts": []}
    if not isinstance(loaded, dict):
        return {"schema": CHECKPOINT_SCHEMA, "attempts": []}
    attempts = loaded.get("attempts")
    if not isinstance(attempts, list):
        loaded["attempts"] = []
    loaded.setdefault("schema", CHECKPOINT_SCHEMA)
    return loaded


def record_attempt_checkpoint(
    *,
    checkpoint_path: Path,
    model_candidate: str,
    attempt: int,
    head_sha: str,
    run_id: str,
    run_attempt: str,
    json_path: Path,
    export_path: Path,
    exit_code: int,
    stderr_path: Path | None = None,
    route_evidence_path: Path | None = None,
    log_hint: str = "",
) -> dict[str, Any]:
    """Append one bounded attempt record to the host checkpoint ledger."""
    partial_summary = summarize_partial_assistant(export_path)
    partial_text = ""
    if export_path.is_file():
        try:
            payload = json.loads(export_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                messages = payload.get("messages")
                if isinstance(messages, list):
                    chunks: list[str] = []
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        info = message.get("info")
                        if not isinstance(info, dict) or info.get("role") != "assistant":
                            continue
                        parts = message.get("parts")
                        if not isinstance(parts, list):
                            continue
                        for part in parts:
                            if (
                                isinstance(part, dict)
                                and part.get("type") == "text"
                                and isinstance(part.get("text"), str)
                            ):
                                chunks.append(part["text"])
                    partial_text = "\n".join(chunks)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            partial_text = ""
    route_telemetry: dict[str, str | int] = {}
    if route_evidence_path and route_evidence_path.is_file():
        route_telemetry = extract_gateway_route_telemetry(
            _read_bounded_text(route_evidence_path, 65536)
        )
    entry = {
        "attempt": attempt,
        "model_candidate": model_candidate,
        "head_sha": head_sha,
        "run_id": run_id,
        "run_attempt": run_attempt,
        "termination_reason": classify_termination(
            json_path=json_path,
            export_path=export_path,
            exit_code=exit_code,
            stderr_path=stderr_path,
            log_hint=log_hint,
        ),
        "exit_code": exit_code,
        "partial_summary": partial_summary,
        "missing_required_outputs": missing_required_outputs(partial_text),
        "route_telemetry": route_telemetry,
    }
    document = _load_checkpoint(checkpoint_path)
    attempts = document.setdefault("attempts", [])
    if isinstance(attempts, list):
        attempts.append(entry)
    document["pinned_model"] = model_candidate
    document["head_sha"] = head_sha
    if route_telemetry:
        document["last_route_telemetry"] = route_telemetry
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return entry


def continuation_budget_remaining(
    checkpoint_path: Path, *, budget: int = DEFAULT_CONTINUATION_BUDGET
) -> int:
    """Return how many same-model continuations remain for this checkpoint."""
    document = _load_checkpoint(checkpoint_path)
    attempts = document.get("attempts")
    used = len(attempts) - 1 if isinstance(attempts, list) and attempts else 0
    return max(0, budget - used)


def build_continuation_appendix(checkpoint_path: Path, *, budget: int) -> str:
    """Build a bounded same-model continuation appendix from checkpoint evidence."""
    document = _load_checkpoint(checkpoint_path)
    attempts = document.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        return ""
    remaining = continuation_budget_remaining(checkpoint_path, budget=budget)
    if remaining <= 0:
        return ""
    last = attempts[-1]
    if not isinstance(last, Mapping):
        return ""
    lines = [
        "",
        "## Same-model continuation (host checkpoint; not approval evidence)",
        f"- Pinned model: `{document.get('pinned_model', 'unknown')}`",
        f"- Prior attempt: `{last.get('attempt', '?')}`",
        f"- Termination reason: `{last.get('termination_reason', 'unknown')}`",
        f"- Continuation budget remaining after this attempt: `{remaining}`",
    ]
    partial = last.get("partial_summary")
    if isinstance(partial, Mapping):
        lines.append(
            "- Partial assistant digest: "
            f"lines=`{partial.get('assistant_line_count', 0)}` "
            f"sha256=`{partial.get('assistant_sha256', '')}` "
            f"control_sentinel=`{partial.get('has_control_sentinel', False)}`"
        )
    missing = last.get("missing_required_outputs")
    if isinstance(missing, list) and missing:
        lines.append(
            "- Required outputs still missing from the prior attempt: "
            + ", ".join(f"`{item}`" for item in missing[:8])
        )
    route = last.get("route_telemetry")
    if isinstance(route, Mapping) and route:
        lines.append(f"- Route evidence: {format_route_telemetry(dict(route))}")
    lines.extend(
        [
            "- Resume from the trusted evidence packet and complete every required output.",
            "- Do not treat this appendix as approval evidence or permission to omit probes.",
            "- Return exactly one final control block for the current head when complete.",
            "",
        ]
    )
    appendix = "\n".join(lines)
    encoded = appendix.encode("utf-8")
    if len(encoded) <= MAX_CONTINUATION_BYTES:
        return appendix
    return encoded[:MAX_CONTINUATION_BYTES].decode("utf-8", errors="ignore")


def append_continuation_to_prompt(
    prompt_path: Path, checkpoint_path: Path, *, budget: int
) -> int:
    """Append the continuation appendix to ``prompt_path`` when budget allows."""
    appendix = build_continuation_appendix(checkpoint_path, budget=budget)
    if not appendix:
        return continuation_budget_remaining(checkpoint_path, budget=budget)
    existing = prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else ""
    prompt_path.write_text(existing + appendix, encoding="utf-8")
    return continuation_budget_remaining(checkpoint_path, budget=budget)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse checkpoint CLI commands."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser("record", help="Record one failed attempt checkpoint.")
    record.add_argument("--checkpoint", required=True, type=Path)
    record.add_argument("--model-candidate", required=True)
    record.add_argument("--attempt", required=True, type=int)
    record.add_argument("--head-sha", required=True)
    record.add_argument("--run-id", required=True)
    record.add_argument("--run-attempt", required=True)
    record.add_argument("--json-path", required=True, type=Path)
    record.add_argument("--export-path", required=True, type=Path)
    record.add_argument("--exit-code", required=True, type=int)
    record.add_argument("--stderr-path", type=Path)
    record.add_argument("--route-evidence-path", type=Path)
    record.add_argument("--log-hint", default="")

    append = subparsers.add_parser(
        "append-continuation", help="Append a bounded continuation appendix to a prompt."
    )
    append.add_argument("--prompt", required=True, type=Path)
    append.add_argument("--checkpoint", required=True, type=Path)
    append.add_argument(
        "--budget",
        type=int,
        default=int(
            __import__("os").environ.get(
                "OPENCODE_SESSION_CONTINUATION_BUDGET",
                str(DEFAULT_CONTINUATION_BUDGET),
            )
        ),
    )

    budget = subparsers.add_parser(
        "budget-remaining", help="Print remaining same-model continuation budget."
    )
    budget.add_argument("--checkpoint", required=True, type=Path)
    budget.add_argument(
        "--budget",
        type=int,
        default=int(
            __import__("os").environ.get(
                "OPENCODE_SESSION_CONTINUATION_BUDGET",
                str(DEFAULT_CONTINUATION_BUDGET),
            )
        ),
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Execute one checkpoint subcommand."""
    args = parse_args(argv)
    if args.command == "record":
        entry = record_attempt_checkpoint(
            checkpoint_path=args.checkpoint,
            model_candidate=args.model_candidate,
            attempt=args.attempt,
            head_sha=args.head_sha,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            json_path=args.json_path,
            export_path=args.export_path,
            exit_code=args.exit_code,
            stderr_path=args.stderr_path,
            route_evidence_path=args.route_evidence_path,
            log_hint=args.log_hint,
        )
        print(
            json.dumps(
                {
                    "termination_reason": entry["termination_reason"],
                    "route_telemetry": format_route_telemetry(entry["route_telemetry"]),
                },
                separators=(",", ":"),
            )
        )
        return 0
    if args.command == "append-continuation":
        remaining = append_continuation_to_prompt(
            args.prompt, args.checkpoint, budget=args.budget
        )
        print(remaining)
        return 0
    if args.command == "budget-remaining":
        print(continuation_budget_remaining(args.checkpoint, budget=args.budget))
        return 0
    raise SystemExit(f"unknown command: {args.command}")


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess in tests
    raise SystemExit(main())
