#!/usr/bin/env python3
"""Dispatch Noema after a current-head OpenCode approval and await its verdict."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from typing import Any, TextIO

from scripts.ci.opencode_existing_approval_gate import (
    flatten_reviews,
    has_reusable_real_model_approval,
)
from scripts.ci.redact_sensitive_log import redact_text


REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
NOEMA_REVIEW_MARKER = "<!-- noema-review-gate "
TERMINAL_NOEMA_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}


GhRunner = Callable[[Sequence[str], str | None], str]
ApprovalChecker = Callable[..., bool]


def run_gh(args: Sequence[str], stdin: str | None = None) -> str:
    """Run a GitHub CLI command without invoking a shell."""
    completed = subprocess.run(
        ["gh", *args],
        check=False,
        input=stdin,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if completed.returncode != 0:
        detail = redact_text(completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            detail or f"gh command failed with exit code {completed.returncode}"
        )
    return completed.stdout


def fetch_head(repo: str, number: int, *, runner: GhRunner = run_gh) -> str:
    """Return the live pull request head SHA."""
    return runner(
        ["api", f"repos/{repo}/pulls/{number}", "--jq", ".head.sha // empty"],
        None,
    ).strip()


def fetch_reviews(
    repo: str,
    number: int,
    *,
    runner: GhRunner = run_gh,
) -> list[dict[str, Any]]:
    """Return the complete flattened pull request review history."""
    document = json.loads(
        runner(
            [
                "api",
                "--paginate",
                "--slurp",
                f"repos/{repo}/pulls/{number}/reviews",
            ],
            None,
        )
        or "[]"
    )
    return flatten_reviews(document)


def noema_review_state(reviews: list[dict[str, Any]], head_sha: str) -> str | None:
    """Return Noema's latest terminal verdict for the exact current head."""
    for review in reversed(reviews):
        if str(review.get("commit_id") or "").lower() != head_sha.lower():
            continue
        if NOEMA_REVIEW_MARKER not in str(review.get("body") or ""):
            continue
        state = str(review.get("state") or "").upper()
        if state in TERMINAL_NOEMA_STATES:
            return state
    return None


def dispatch_noema(
    repo: str,
    number: int,
    head_sha: str,
    *,
    runner: GhRunner = run_gh,
) -> None:
    """Dispatch the target repository's default-branch Noema workflow."""
    payload = {
        "event_type": "noema-review",
        "client_payload": {
            "target_repository": repo,
            "pr_number": number,
            "pr_head_sha": head_sha,
        },
    }
    runner(
        ["api", "-X", "POST", f"repos/{repo}/dispatches", "--input", "-"],
        json.dumps(payload),
    )


def run_handoff(
    repo: str,
    number: int,
    head_sha: str,
    *,
    attempts: int,
    interval_seconds: float,
    runner: GhRunner = run_gh,
    sleeper: Callable[[float], None] = time.sleep,
    approval_checker: ApprovalChecker = has_reusable_real_model_approval,
    log: TextIO | None = None,
) -> int:
    """Verify OpenCode, dispatch Noema, and wait for an exact-head verdict."""
    log = log or sys.stderr
    live_head = fetch_head(repo, number, runner=runner)
    if live_head.lower() != head_sha.lower():
        print(
            "Noema handoff refused stale input: "
            f"expected head {head_sha}, observed {live_head or '<missing>'}.",
            file=log,
        )
        return 2

    reviews = fetch_reviews(repo, number, runner=runner)
    if not approval_checker(reviews, head_sha, log=log):
        print(
            "Noema handoff skipped because the exact head has no reusable "
            "OpenCode App real-model approval.",
            file=log,
        )
        return 1

    state = noema_review_state(reviews, head_sha)
    if state is not None:
        print(
            f"Noema already published {state} for {repo}#{number} at {head_sha}.",
            file=log,
        )
        return 0 if state == "APPROVED" else 1

    dispatch_noema(repo, number, head_sha, runner=runner)
    print(
        f"Dispatched default-branch Noema review for {repo}#{number} at {head_sha}.",
        file=log,
    )

    for attempt in range(1, attempts + 1):
        live_head = fetch_head(repo, number, runner=runner)
        if live_head.lower() != head_sha.lower():
            print(
                "Noema handoff stopped because the pull request head changed: "
                f"expected {head_sha}, observed {live_head or '<missing>'}.",
                file=log,
            )
            return 2

        reviews = fetch_reviews(repo, number, runner=runner)
        state = noema_review_state(reviews, head_sha)
        if state is not None:
            print(
                f"Noema published {state} for {repo}#{number} at {head_sha} "
                f"after poll {attempt}/{attempts}.",
                file=log,
            )
            return 0 if state == "APPROVED" else 1

        if attempt < attempts:
            sleeper(interval_seconds)

    print(
        f"Noema did not publish an exact-head verdict after {attempts} polls; "
        "the merge scheduler will retain the two-reviewer policy.",
        file=log,
    )
    return 1


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse and validate handoff arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--pr-number", required=True, type=int)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--attempts", type=int, default=90)
    parser.add_argument("--interval-seconds", type=float, default=10.0)
    args = parser.parse_args(argv)
    if not REPOSITORY_RE.fullmatch(args.repo):
        parser.error("--repo must name a ContextualWisdomLab repository")
    if args.pr_number < 1:
        parser.error("--pr-number must be positive")
    if not SHA_RE.fullmatch(args.head_sha):
        parser.error("--head-sha must be a 40-character Git SHA")
    if args.attempts < 1:
        parser.error("--attempts must be positive")
    if args.interval_seconds < 0:
        parser.error("--interval-seconds must be non-negative")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Noema handoff command."""
    args = parse_args(argv)
    return run_handoff(
        args.repo,
        args.pr_number,
        args.head_sha,
        attempts=args.attempts,
        interval_seconds=args.interval_seconds,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
