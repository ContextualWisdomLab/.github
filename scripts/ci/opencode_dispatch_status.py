#!/usr/bin/env python3
"""Decide the repository-dispatch OpenCode status from validated live evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

try:
    from opencode_existing_approval_gate import (
        OPENCODE_APP_APPROVAL_AUTHORS,
        review_rejection_reason,
    )
except ModuleNotFoundError:  # pragma: no cover - package import path
    from scripts.ci.opencode_existing_approval_gate import (
        OPENCODE_APP_APPROVAL_AUTHORS,
        review_rejection_reason,
    )


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
    """Parse commit-status evidence inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-outcome", required=True)
    parser.add_argument("--coverage-result", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--pull-request-file", required=True, type=Path)
    parser.add_argument("--reviews-file", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print one JSON commit-status decision."""
    args = parse_args(argv)
    pull_request = json.loads(args.pull_request_file.read_text(encoding="utf-8"))
    reviews = json.loads(args.reviews_file.read_text(encoding="utf-8"))
    if not isinstance(pull_request, dict) or not isinstance(reviews, list):
        raise SystemExit("pull request evidence must be an object and reviews evidence an array")
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
