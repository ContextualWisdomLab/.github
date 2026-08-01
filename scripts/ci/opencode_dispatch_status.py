#!/usr/bin/env python3
"""Decide the repository-dispatch OpenCode status from validated live evidence."""

from __future__ import annotations

import argparse
import json
import re
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


VISIBILITY_COMMENT_MARKER = "<!-- opencode-dispatch-review-tool-status -->"
VISIBILITY_COMMENT_AUTHORS = frozenset({"opencode-agent", "opencode-agent[bot]"})
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


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


def _bounded_field(value: str, *, fallback: str, limit: int = 240) -> str:
    """Return a one-line bounded field safe for a governance receipt."""
    normalized = " ".join(str(value or "").split())
    return (normalized or fallback)[:limit]


def existing_visibility_comment_id(comments: Sequence[dict[str, Any]]) -> int | None:
    """Return the latest OpenCode App visibility-comment id, if present."""
    for comment in reversed(comments):
        author = str((comment.get("user") or {}).get("login") or "").casefold()
        if author not in VISIBILITY_COMMENT_AUTHORS:
            continue
        if VISIBILITY_COMMENT_MARKER not in str(comment.get("body") or ""):
            continue
        comment_id = comment.get("id")
        if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id < 1:
            continue
        return comment_id
    return None


def visibility_comment(
    *,
    state: str,
    description: str,
    expected_head: str,
    model_outcome: str,
    coverage_result: str,
    run_url: str,
) -> str:
    """Render a bounded exact-head review-tool receipt for the target PR."""
    if not SHA_RE.fullmatch(expected_head):
        raise ValueError("visibility receipt requires a 40-character head SHA")
    result = "RESOLVED" if state == "success" else "REVIEW_TOOL_FAILURE"
    reason = _bounded_field(
        description,
        fallback="OpenCode live approval evidence validation failed.",
    )
    model = _bounded_field(model_outcome, fallback="missing", limit=80)
    coverage = _bounded_field(coverage_result, fallback="missing", limit=80)
    run = _bounded_field(run_url, fallback="unavailable", limit=300)
    posture = (
        "A validated exact-current-head OpenCode approval is now present."
        if state == "success"
        else (
            "This is review-tool evidence, not a source finding or a clean review. "
            "Merge policy remains fail closed until an exact-head formal approval exists."
        )
    )
    return "\n".join(
        [
            VISIBILITY_COMMENT_MARKER,
            "",
            "## OpenCode central review receipt",
            "",
            f"- Result: `{result}`",
            f"- Head SHA: `{expected_head}`",
            f"- Workflow run: {run}",
            f"- Model-pool outcome: `{model}`",
            f"- Coverage evidence: `{coverage}`",
            f"- Reason: {reason}",
            "",
            posture,
        ]
    )


def add_visibility_receipt(
    decision: dict[str, str],
    *,
    comments: Sequence[dict[str, Any]],
    expected_head: str,
    model_outcome: str,
    coverage_result: str,
    run_url: str,
) -> dict[str, Any]:
    """Attach an App-comment upsert decision to a commit-status decision."""
    enriched: dict[str, Any] = dict(decision)
    comment_id = existing_visibility_comment_id(comments)
    state = decision.get("state", "failure")
    enriched["visibility"] = {
        "comment_id": comment_id,
        "should_publish": state != "success" or comment_id is not None,
        "body": visibility_comment(
            state=state,
            description=decision.get("description", ""),
            expected_head=expected_head,
            model_outcome=model_outcome,
            coverage_result=coverage_result,
            run_url=run_url,
        ),
    }
    return enriched


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse commit-status evidence inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-outcome", required=True)
    parser.add_argument("--coverage-result", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--pull-request-file", required=True, type=Path)
    parser.add_argument("--reviews-file", required=True, type=Path)
    parser.add_argument("--comments-file", type=Path)
    parser.add_argument("--run-url", default="")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Print one JSON commit-status decision."""
    args = parse_args(argv)
    pull_request = json.loads(args.pull_request_file.read_text(encoding="utf-8"))
    reviews = json.loads(args.reviews_file.read_text(encoding="utf-8"))
    if not isinstance(pull_request, dict) or not isinstance(reviews, list):
        raise SystemExit("pull request evidence must be an object and reviews evidence an array")
    decision: dict[str, Any] = decide_status(
        model_outcome=args.model_outcome,
        coverage_result=args.coverage_result,
        expected_head=args.expected_head,
        pull_request=pull_request,
        reviews=reviews,
    )
    if args.comments_file is not None:
        comments = json.loads(args.comments_file.read_text(encoding="utf-8"))
        if not isinstance(comments, list):
            raise SystemExit("comments evidence must be an array")
        decision = add_visibility_receipt(
            decision,
            comments=comments,
            expected_head=args.expected_head,
            model_outcome=args.model_outcome,
            coverage_result=args.coverage_result,
            run_url=args.run_url,
        )
    print(json.dumps(decision, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
