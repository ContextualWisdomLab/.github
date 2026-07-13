#!/usr/bin/env python3
"""Validate that a reusable same-head approval came from a real model review."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, TextIO


APPROVAL_AUTHORS = frozenset(
    {"opencode-agent", "opencode-agent[bot]", "github-actions[bot]"}
)
OPENCODE_APP_APPROVAL_AUTHORS = frozenset({"opencode-agent", "opencode-agent[bot]"})
FALLBACK_MARKERS = (
    "deterministic current-head evidence",
    "deterministic fallback approval",
    "model-unavailable evidence fallback",
    "did not emit a usable current-head control block",
    "scope: `unsupported`",
    "model-pool outcome: `unknown`",
)
PRIMARY_APPROVAL_MARKER = (
    "OpenCode reviewed the current-head bounded evidence and found no blocking issues."
)
ADVERSARIAL_BLOCK_RE = re.compile(
    r"## Adversarial validation\s*```json\s*(?P<payload>.*?)\s*```",
    re.IGNORECASE | re.DOTALL,
)
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
WORKFLOW_RUN_RE = re.compile(r"(?m)^- Workflow run: [1-9][0-9]*\s*$")
WORKFLOW_ATTEMPT_RE = re.compile(r"(?m)^- Workflow attempt: [1-9][0-9]*\s*$")
REQUIRED_PROBE_FIELDS = (
    "path",
    "hypothesis",
    "attack_or_counterexample",
    "evidence",
    "outcome",
)


def flatten_reviews(document: object) -> list[dict[str, Any]]:
    """Flatten REST pagination output while rejecting malformed review entries."""
    if not isinstance(document, list):
        raise ValueError("review payload must be a JSON array")

    reviews: list[dict[str, Any]] = []
    for page in document:
        entries = page if isinstance(page, list) else [page]
        for review in entries:
            if not isinstance(review, dict):
                raise ValueError("every review entry must be a JSON object")
            reviews.append(review)
    return reviews


def extract_adversarial_evidence(body: str) -> dict[str, Any] | None:
    """Return the last parseable adversarial-validation JSON block."""
    evidence: dict[str, Any] | None = None
    for match in ADVERSARIAL_BLOCK_RE.finditer(body):
        try:
            candidate = json.loads(match.group("payload"))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            evidence = candidate
    return evidence


def adversarial_rejection_reason(body: str) -> str | None:
    """Explain why structured adversarial evidence is not reusable."""
    evidence = extract_adversarial_evidence(body)
    if evidence is None:
        return "missing parseable adversarial-validation JSON"
    if str(evidence.get("status") or "").lower() != "passed":
        return "adversarial-validation status is not passed"

    probes = evidence.get("probes")
    if not isinstance(probes, list) or not probes:
        return "adversarial-validation probes are empty"
    for probe in probes:
        if not isinstance(probe, dict):
            return "adversarial-validation probe is not an object"
        line = probe.get("line")
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            return "adversarial-validation probe line is not a positive integer"
        for field in REQUIRED_PROBE_FIELDS:
            if not isinstance(probe.get(field), str) or not probe[field].strip():
                return f"adversarial-validation probe is missing {field}"
        if probe["outcome"].strip().lower() != "falsified":
            return "approval probe outcome is not falsified"

    residual_risk = evidence.get("residual_risk")
    if not isinstance(residual_risk, str) or not residual_risk.strip():
        return "adversarial-validation residual_risk is missing"
    return None


def review_rejection_reason(
    review: dict[str, Any],
    head_sha: str,
    *,
    approval_authors: frozenset[str] = APPROVAL_AUTHORS,
) -> str | None:
    """Explain why a review cannot prove a real current-head model approval."""
    if str(review.get("state") or "").upper() != "APPROVED":
        return "review state is not APPROVED"
    if str(review.get("commit_id") or "").lower() != head_sha.lower():
        return "review commit does not match current head"

    login = str((review.get("user") or {}).get("login") or "")
    if login not in approval_authors:
        return "review author is not an allowed OpenCode publication actor"

    body = str(review.get("body") or "")
    body_lower = body.lower()
    if any(marker in body_lower for marker in FALLBACK_MARKERS):
        return "review body is deterministic or model-unavailable fallback evidence"
    if PRIMARY_APPROVAL_MARKER not in body:
        return "review body lacks the real-model approval marker"
    if "- Result: APPROVE" not in body:
        return "review body lacks an APPROVE result"
    if f"- Head SHA: `{head_sha}`" not in body:
        return "review body lacks the exact current-head SHA"
    if not WORKFLOW_RUN_RE.search(body):
        return "review body lacks a workflow run id"
    if not WORKFLOW_ATTEMPT_RE.search(body):
        return "review body lacks a workflow attempt"
    return adversarial_rejection_reason(body)


def has_reusable_real_model_approval(
    reviews: list[dict[str, Any]],
    head_sha: str,
    *,
    log: TextIO,
    approval_authors: frozenset[str] = APPROVAL_AUTHORS,
) -> bool:
    """Return whether reviews contain a real-model approval for the exact head."""
    candidate_count = 0
    for review in reversed(reviews):
        state = str(review.get("state") or "").upper()
        commit_id = str(review.get("commit_id") or "")
        login = str((review.get("user") or {}).get("login") or "")
        if state != "APPROVED" or commit_id.lower() != head_sha.lower():
            continue
        if login not in APPROVAL_AUTHORS:
            continue
        candidate_count += 1
        reason = review_rejection_reason(
            review,
            head_sha,
            approval_authors=approval_authors,
        )
        review_id = review.get("id", "unknown")
        if reason is None:
            print(
                "existing-approval gate accepted real-model review "
                f"id={review_id} author={login} head={head_sha}",
                file=log,
            )
            return True
        print(
            "existing-approval gate rejected same-head review "
            f"id={review_id} author={login}: {reason}",
            file=log,
        )

    print(
        "existing-approval gate found no reusable real-model approval "
        f"for head={head_sha}; same-head candidates={candidate_count}",
        file=log,
    )
    return False


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse existing-approval gate command-line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--head", required=True)
    parser.add_argument(
        "--require-opencode-app",
        action="store_true",
        help="accept only reviews authored by the OpenCode GitHub App",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Read paginated reviews from stdin and evaluate reusable approval evidence."""
    args = parse_args(argv)
    if not SHA_RE.fullmatch(args.head):
        print("existing-approval gate requires a 40-character head SHA", file=sys.stderr)
        return 2
    try:
        reviews = flatten_reviews(json.load(sys.stdin))
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"existing-approval gate could not parse reviews: {exc}", file=sys.stderr)
        return 2
    approval_authors = (
        OPENCODE_APP_APPROVAL_AUTHORS
        if args.require_opencode_app
        else APPROVAL_AUTHORS
    )
    return (
        0
        if has_reusable_real_model_approval(
            reviews,
            args.head,
            log=sys.stderr,
            approval_authors=approval_authors,
        )
        else 1
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
