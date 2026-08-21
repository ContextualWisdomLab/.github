#!/usr/bin/env python3
"""Decide the repository-dispatch OpenCode status from validated live evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

try:
    from opencode_existing_approval_gate import (
        FALLBACK_MARKERS,
        OPENCODE_APP_APPROVAL_AUTHORS,
        review_rejection_reason,
    )
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.ci.opencode_existing_approval_gate import (
        FALLBACK_MARKERS,
        OPENCODE_APP_APPROVAL_AUTHORS,
        review_rejection_reason,
    )


OPENCODE_VERDICT_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED"})
MISSING_VERDICT_MESSAGE = (
    "No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head. "
    "This required check is not a review and must not succeed until the "
    "authenticated dispatch posts a current-head verdict."
)


def current_head_opencode_verdict(
    reviews: Sequence[dict[str, Any]], head_sha: str
) -> str | None:
    """Return the latest substantive current-head OpenCode verdict, if any."""
    expected = (head_sha or "").lower()
    if not expected:
        return None
    for review in reversed(reviews):
        author = str((review.get("user") or {}).get("login") or "").casefold()
        if author not in OPENCODE_APP_APPROVAL_AUTHORS:
            continue
        if str(review.get("commit_id") or "").lower() != expected:
            continue
        state = str(review.get("state") or "").upper()
        if state not in OPENCODE_VERDICT_STATES:
            return None
        body = str(review.get("body") or "").casefold()
        if state == "APPROVED" and any(marker in body for marker in FALLBACK_MARKERS):
            return None
        return state
    return None


def decide_required_verdict_check(
    *,
    expected_head: str,
    pull_request: dict[str, Any],
    reviews: Sequence[dict[str, Any]],
) -> dict[str, str]:
    """Fail closed unless OpenCode already published a current-head verdict."""
    live_head = str((pull_request.get("head") or {}).get("sha") or "")
    if not expected_head or live_head.lower() != expected_head.lower():
        return {
            "state": "failure",
            "description": (
                "OpenCode required-check target is stale or the live PR head "
                "is unavailable."
            ),
        }
    verdict = current_head_opencode_verdict(reviews, expected_head)
    if verdict is None:
        return {"state": "failure", "description": MISSING_VERDICT_MESSAGE}
    return {
        "state": "success",
        "description": f"Current-head OpenCode verdict: {verdict}.",
    }


def _has_current_approval(reviews: Sequence[dict[str, Any]], head_sha: str) -> bool:
    """Return whether the latest OpenCode decision is a verified approval."""
    for review in reversed(reviews):
        author = str((review.get("user") or {}).get("login") or "").casefold()
        if author not in OPENCODE_APP_APPROVAL_AUTHORS:
            continue
        if str(review.get("commit_id") or "").lower() != head_sha.lower():
            continue
        return (
            review_rejection_reason(
                review,
                head_sha,
                approval_authors=OPENCODE_APP_APPROVAL_AUTHORS,
            )
            is None
        )
    return False


def decide_status(
    *,
    model_outcome: str,
    coverage_result: str,
    expected_head: str,
    pull_request: dict[str, Any],
    reviews: Sequence[dict[str, Any]],
) -> dict[str, str]:
    """Return a fail-closed GitHub commit-status decision."""
    live_head = str((pull_request.get("head") or {}).get("sha") or "")
    if coverage_result != "success":
        reason = "OpenCode coverage evidence did not pass for the current head."
    elif not expected_head or live_head.lower() != expected_head.lower():
        reason = "OpenCode status target is stale or the live PR head is unavailable."
    elif not _has_current_approval(reviews, expected_head):
        reason = (
            "No validated exact-current-head OpenCode approval was published"
            f" (model outcome: {model_outcome or 'missing'})."
        )
    else:
        return {
            "state": "success",
            "description": "Validated current-head OpenCode approval and coverage passed.",
        }
    return {"state": "failure", "description": reason}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse commit-status or required-verdict evidence inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("dispatch-status", "required-verdict"),
        default="dispatch-status",
    )
    parser.add_argument("--model-outcome")
    parser.add_argument("--coverage-result")
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--pull-request-file", required=True, type=Path)
    parser.add_argument("--reviews-file", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print one JSON decision and exit 1 when the required verdict is missing."""
    args = parse_args(argv)
    pull_request = json.loads(args.pull_request_file.read_text(encoding="utf-8"))
    reviews = json.loads(args.reviews_file.read_text(encoding="utf-8"))
    if not isinstance(pull_request, dict) or not isinstance(reviews, list):
        raise SystemExit("pull request evidence must be an object and reviews evidence an array")
    if args.mode == "required-verdict":
        decision = decide_required_verdict_check(
            expected_head=args.expected_head,
            pull_request=pull_request,
            reviews=reviews,
        )
        print(json.dumps(decision, separators=(",", ":")))
        return 0 if decision["state"] == "success" else 1
    if not args.model_outcome or not args.coverage_result:
        raise SystemExit("--model-outcome and --coverage-result are required")
    print(
        json.dumps(
            decide_status(
                model_outcome=args.model_outcome,
                coverage_result=args.coverage_result,
                expected_head=args.expected_head,
                pull_request=pull_request,
                reviews=reviews,
            ),
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
