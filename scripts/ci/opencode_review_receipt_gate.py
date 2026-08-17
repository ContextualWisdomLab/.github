#!/usr/bin/env python3
"""Require a current-head formal OpenCode review receipt before a required check is green."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
HEAD_SHA_IN_BODY_RE = re.compile(r"Head SHA:\s*`([0-9a-fA-F]{40})`")
FORMAL_AUTHORS = frozenset(
    {"opencode-agent", "opencode-agent[bot]", "github-actions[bot]"}
)
FORMAL_STATES = frozenset({"APPROVED", "CHANGES_REQUESTED", "COMMENTED"})
STATUS_HEADINGS = ("## OpenCode Review Status", "## OpenCode 게이트 상태")
PRODUCT_MARKERS = (
    "## Pull request overview",
    "## Pull request 개요",
    "## Changed files",
    "## Changed API",
    "## Verdict",
    "opencode-review-control-v1",
    "OpenCode reviewed the current-head product diff",
    "OpenCode reviewed the current-head bounded evidence",
)
MENTION_RE = re.compile(r"^@opencode-agent\b", re.IGNORECASE)

AFIPC_230_HEAD = "5eda857066c9207786d3bdde49826f8f94b98c12"
AFIPC_230_STALE_HEADS = frozenset(
    {
        "8a1133d406d0d15b425644e0dc3910f112ccbb36",
        "8757e7b022cb66f21886d4c241857a9986ef7a6c",
    }
)
KAEFA_79_HEAD = "1c5d9f0491fc178be3f7f307dac521fbcbba6978"


class ReceiptGateError(ValueError):
    """Raised when the required OpenCode check lacks a current-head formal receipt."""


def review_author(review: Mapping[str, Any]) -> str:
    """Return the login for a REST or GraphQL review object."""
    user = review.get("user") or review.get("author") or {}
    if isinstance(user, Mapping):
        return str(user.get("login") or "").strip()
    return ""


def review_commit(review: Mapping[str, Any]) -> str:
    """Return the commit SHA the review was submitted against."""
    commit_id = str(review.get("commit_id") or "").strip()
    if commit_id:
        return commit_id
    commit = review.get("commit") or {}
    if isinstance(commit, Mapping):
        return str(commit.get("oid") or commit.get("sha") or "").strip()
    return ""


def review_body_head_sha(review: Mapping[str, Any]) -> str | None:
    """Return the last explicit Head SHA recorded in a review body."""
    matches = HEAD_SHA_IN_BODY_RE.findall(str(review.get("body") or ""))
    return matches[-1] if matches else None


def review_matches_head(review: Mapping[str, Any], head_sha: str) -> bool:
    """Return whether commit and optional body SHA both match the live head."""
    if not head_sha or review_commit(review).lower() != head_sha.lower():
        return False
    body_head = review_body_head_sha(review)
    return body_head is None or body_head.lower() == head_sha.lower()


def is_mention_or_malformed(body: str) -> bool:
    """Return whether a body is a mention payload or not a product-file review."""
    stripped = body.strip()
    if not stripped:
        return True
    first_line = stripped.splitlines()[0].strip()
    if MENTION_RE.match(first_line) and "Head SHA:" not in stripped:
        return True
    if any(heading in stripped for heading in STATUS_HEADINGS) and not any(
        marker in stripped for marker in PRODUCT_MARKERS
    ):
        return True
    return not any(marker in stripped for marker in PRODUCT_MARKERS)


def is_formal_receipt(
    review: Mapping[str, Any],
    head_sha: str,
    *,
    is_draft: bool,
) -> tuple[bool, str]:
    """Return whether a review is a usable current-head formal product-file receipt."""
    if not review_matches_head(review, head_sha):
        return False, "stale or mismatched head"
    author = review_author(review)
    if author not in FORMAL_AUTHORS:
        return False, f"author {author or '<empty>'} is not an OpenCode publisher"
    state = str(review.get("state") or "").upper()
    if state not in FORMAL_STATES:
        return False, f"state {state or '<empty>'} is not a formal review verdict"
    if not review.get("id"):
        return False, "missing pullrequestreview id"
    body = str(review.get("body") or "")
    if is_mention_or_malformed(body):
        return False, "mention, status-only, or malformed payload is not a formal review"
    if is_draft and state == "APPROVED":
        return False, "draft must never receive bot APPROVE"
    return True, "current-head formal review"


def evaluate_receipts(
    reviews: Sequence[Mapping[str, Any]],
    head_sha: str,
    *,
    is_draft: bool = False,
) -> tuple[Mapping[str, Any] | None, str]:
    """Return the current-head formal receipt or explain why the gate fails."""
    if not SHA_RE.fullmatch(head_sha):
        return None, "receipt gate requires a 40-character head SHA"
    stale_hits = 0
    for review in reversed(list(reviews)):
        if not isinstance(review, Mapping):
            continue
        commit = review_commit(review)
        if commit and commit.lower() != head_sha.lower():
            stale_hits += 1
            continue
        ok, reason = is_formal_receipt(review, head_sha, is_draft=is_draft)
        if ok:
            return review, reason
        if "never receive bot APPROVE" in reason:
            return None, reason
        if reason.startswith("stale"):
            stale_hits += 1
    if stale_hits:
        return (
            None,
            "stale CHANGES_REQUESTED or prior-head reviews are not current-head receipts",
        )
    return None, "no current-head formal OpenCode review receipt"


def load_reviews(path: str | None) -> list[Mapping[str, Any]]:
    """Load review objects from a JSON file or stdin."""
    raw = sys.stdin.read() if not path or path == "-" else Path(path).read_text(encoding="utf-8")
    loaded = json.loads(raw)
    if not isinstance(loaded, list):
        raise ReceiptGateError("review payload must be a JSON array")
    return [item for item in loaded if isinstance(item, Mapping)]


def fetch_reviews(repo: str, number: int) -> list[Mapping[str, Any]]:
    """Read pull-request reviews through gh without invoking a shell."""
    completed = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{number}/reviews",
            "--paginate",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "gh reviews lookup failed").strip()
        raise ReceiptGateError(f"formal review receipt lookup failed: {detail}")
    loaded = json.loads(completed.stdout or "[]")
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, Mapping)]
    raise ReceiptGateError("formal review receipt lookup returned malformed JSON")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse receipt-gate CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default="")
    parser.add_argument("--pr-number", type=int, default=0)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--draft", action="store_true")
    parser.add_argument("--reviews-file")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Fail closed unless a verifiable current-head formal review receipt exists."""
    args = parse_args(argv)
    try:
        if args.reviews_file:
            reviews = load_reviews(args.reviews_file)
        elif args.repo and args.pr_number > 0:
            reviews = fetch_reviews(args.repo, args.pr_number)
        else:
            raise ReceiptGateError("receipt gate needs --reviews-file or --repo/--pr-number")
        receipt, reason = evaluate_receipts(
            reviews, args.head_sha, is_draft=args.draft
        )
        if receipt is None:
            raise ReceiptGateError(reason)
    except (ReceiptGateError, json.JSONDecodeError, OSError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as handle:
                handle.write("## OpenCode formal review receipt missing\n\n")
                handle.write(f"{exc}\n")
        return 1
    review_id = receipt.get("id")
    print(
        f"Current-head formal OpenCode receipt id={review_id} "
        f"state={receipt.get('state')} head={args.head_sha}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
