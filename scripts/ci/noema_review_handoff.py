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

if __package__:
    from scripts.ci.opencode_existing_approval_gate import (
        flatten_reviews,
        has_reusable_real_model_approval,
    )
    from scripts.ci.redact_sensitive_log import redact_text
else:  # pragma: no cover - exercised by the standalone CLI regression test
    from opencode_existing_approval_gate import (
        flatten_reviews,
        has_reusable_real_model_approval,
    )
    from redact_sensitive_log import redact_text


REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/(?!.*(?:\.\.|\.$|^\.))[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
GH_COMMAND_TIMEOUT_SECONDS = 60.0
MAX_TRANSIENT_BACKOFF_MULTIPLIER = 4
NOEMA_REVIEW_AUTHOR = "cwl-noema-review[bot]"
NOEMA_REVIEW_MARKER = "<!-- noema-review-gate "
TERMINAL_NOEMA_STATES = {"APPROVED", "CHANGES_REQUESTED", "COMMENTED"}


GhRunner = Callable[[Sequence[str], str | None], str]
ApprovalChecker = Callable[..., bool]


def run_gh(args: Sequence[str], stdin: str | None = None) -> str:
    """Run a GitHub CLI command without invoking a shell."""
    try:
        completed = subprocess.run(
            ["gh", *args],
            check=False,
            input=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=GH_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"gh command timed out after {GH_COMMAND_TIMEOUT_SECONDS:g} seconds"
        ) from None
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
        author = str((review.get("user") or {}).get("login") or "").lower()
        if author != NOEMA_REVIEW_AUTHOR:
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


def transient_backoff_seconds(consecutive_failures: int, interval_seconds: float) -> float:
    """Return bounded exponential backoff based on the configured poll interval."""
    exponent = max(consecutive_failures - 1, 0)
    multiplier = min(2**exponent, MAX_TRANSIENT_BACKOFF_MULTIPLIER)
    return interval_seconds * multiplier


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
    dispatched = False
    consecutive_failures = 0
    for attempt in range(1, attempts + 1):
        try:
            live_head = fetch_head(repo, number, runner=runner)
            reviews = fetch_reviews(repo, number, runner=runner)
        except RuntimeError as exc:
            consecutive_failures += 1
            detail = redact_text(str(exc)).strip() or "GitHub API call failed"
            if attempt < attempts:
                delay = transient_backoff_seconds(
                    consecutive_failures,
                    interval_seconds,
                )
                print(
                    "Transient GitHub API failure during Noema handoff "
                    f"poll {attempt}/{attempts}: {detail}; retrying in {delay:g}s.",
                    file=log,
                )
                sleeper(delay)
            else:
                print(
                    "Noema handoff exhausted its bounded polls after a transient "
                    f"GitHub API failure: {detail}.",
                    file=log,
                )
            continue

        if live_head.lower() != head_sha.lower():
            action = (
                "stopped because the pull request head changed"
                if dispatched
                else "refused stale input because the pull request head changed"
            )
            print(
                f"Noema handoff {action}: "
                f"expected {head_sha}, observed {live_head or '<missing>'}.",
                file=log,
            )
            return 2

        if not dispatched and not approval_checker(reviews, head_sha, log=log):
            print(
                "Noema handoff skipped because the exact head has no reusable "
                "OpenCode App real-model approval.",
                file=log,
            )
            return 1

        state = noema_review_state(reviews, head_sha)
        if state is not None:
            timing = "already published" if not dispatched else "published"
            print(
                f"Noema {timing} {state} for {repo}#{number} at {head_sha} "
                f"after poll {attempt}/{attempts}.",
                file=log,
            )
            return 0 if state == "APPROVED" else 1

        if not dispatched:
            try:
                dispatch_noema(repo, number, head_sha, runner=runner)
            except RuntimeError as exc:
                consecutive_failures += 1
                detail = redact_text(str(exc)).strip() or "GitHub API call failed"
                if attempt < attempts:
                    delay = transient_backoff_seconds(
                        consecutive_failures,
                        interval_seconds,
                    )
                    print(
                        "Transient GitHub API failure while dispatching Noema "
                        f"on poll {attempt}/{attempts}: {detail}; "
                        f"retrying in {delay:g}s.",
                        file=log,
                    )
                    sleeper(delay)
                else:
                    print(
                        "Noema dispatch exhausted its bounded polls after a "
                        f"transient GitHub API failure: {detail}.",
                        file=log,
                    )
                continue
            dispatched = True
            print(
                f"Dispatched default-branch Noema review for {repo}#{number} "
                f"at {head_sha}.",
                file=log,
            )

        consecutive_failures = 0
        if attempt < attempts:
            sleeper(interval_seconds)

    if dispatched:
        print(
            f"Noema did not publish an exact-head verdict after {attempts} polls; "
            "the merge scheduler will retain the two-reviewer policy.",
            file=log,
        )
    else:
        print(
            f"Noema was not dispatched after {attempts} bounded polls; "
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
