#!/usr/bin/env python3
"""Dispatch conservative PR autofix runs for actionable review feedback."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
from typing import Any

try:
    from pr_review_merge_scheduler import (
        fetch_open_prs,
        fetch_pr,
        has_current_head_changes_requested,
        is_opencode_review,
        review_matches_current_head,
        run,
        unresolved_thread_count,
    )
except ModuleNotFoundError:
    from scripts.ci.pr_review_merge_scheduler import (
        fetch_open_prs,
        fetch_pr,
        has_current_head_changes_requested,
        is_opencode_review,
        review_matches_current_head,
        run,
        unresolved_thread_count,
    )


DEFAULT_AUTOFIX_REPOSITORY = "ContextualWisdomLab/.github"
FIX_MARKER = "<!-- pr-review-fix-scheduler autofix-dispatch"
FIX_MARKER_RE = re.compile(
    r"<!-- pr-review-fix-scheduler autofix-dispatch "
    r"head_sha=([0-9a-fA-F]{40}) epoch=([0-9]+) -->"
)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
NON_AUTOFIX_CHANGE_REQUEST_MARKERS = (
    "merge conflict",
    "mergestatestatus `dirty`",
    "mergestatestatus dirty",
    "model pool exhausted",
    "could not establish approval sufficiency",
    "unresolved human review thread",
    "unresolved reviewer thread",
    "unresolved reviewer or review-agent thread",
    "failed check",
    "failed-check",
    "coverage-evidence",
    "strix failed",
)


def run_json(args: list[str]) -> Any:
    """Run gh and decode JSON."""
    return json.loads(run(["gh", *args]) or "null")


def issue_comments(repo: str, number: int) -> list[dict[str, Any]]:
    """Return issue comments for a PR."""
    pages = run_json(["api", f"repos/{repo}/issues/{number}/comments", "--paginate", "--slurp"])
    return [comment for page in pages for comment in page]


def recent_fix_marker_exists(
    comments: list[dict[str, Any]],
    head_sha: str,
    min_interval_seconds: int,
) -> bool:
    """Return whether this head was already dispatched recently."""
    now = int(time.time())
    for comment in reversed(comments):
        match = FIX_MARKER_RE.search(str(comment.get("body") or ""))
        if not match or match.group(1).lower() != head_sha.lower():
            continue
        return now - int(match.group(2)) < min_interval_seconds
    return False


def same_repository_head(repo: str, pr: dict[str, Any]) -> bool:
    """Return whether the PR head can be mutated by repository workflow credentials."""
    return ((pr.get("headRepository") or {}).get("nameWithOwner") or "") == repo


def latest_current_head_opencode_review(pr: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest OpenCode review for the current head, if present."""
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if is_opencode_review(review) and review_matches_current_head(review, pr):
            return review
    return None


def change_request_is_autofixable(pr: dict[str, Any]) -> bool:
    """Return whether the latest OpenCode request is safe for bot autofix."""
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if merge_state and merge_state not in {"CLEAN", "HAS_HOOKS"}:
        return False

    review = latest_current_head_opencode_review(pr)
    if review is None:
        return False
    body = str((review or {}).get("body") or "").lower()
    if any(marker in body for marker in NON_AUTOFIX_CHANGE_REQUEST_MARKERS):
        return False
    return True


def needs_autofix(pr: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return whether current-head evidence justifies an autofix attempt."""
    reasons: list[str] = []
    if has_current_head_changes_requested(pr) and change_request_is_autofixable(pr):
        reasons.append("current-head OpenCode requested changes")
    unresolved = unresolved_thread_count(pr)
    if unresolved:
        reasons.append(f"{unresolved} active unresolved review thread(s)")
    return bool(reasons), tuple(reasons)


def create_fix_marker(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Write a head-scoped dispatch marker comment."""
    number = int(pr["number"])
    head_sha = str(pr["headRefOid"])
    body = "\n".join(
        [
            f"{FIX_MARKER} head_sha={head_sha} epoch={int(time.time())} -->",
            "",
            "Scheduled review-feedback autofix for this PR head.",
            "",
            f"- Head SHA: `{head_sha}`",
        ]
    )
    if dry_run:
        print(f"DRY-RUN: would create autofix marker on PR #{number}")
        return
    run(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{repo}/issues/{number}/comments",
            "-f",
            f"body={body}",
        ]
    )


def dispatch_autofix(
    repo: str,
    pr: dict[str, Any],
    *,
    workflow: str,
    workflow_repository: str,
    dry_run: bool,
) -> None:
    """Dispatch an autofix worker for the exact PR head."""
    dispatch_repo = workflow_repository or repo
    args = [
        "gh",
        "workflow",
        "run",
        workflow,
        "--repo",
        dispatch_repo,
    ]
    if dispatch_repo != repo:
        args.extend(["-f", f"target_repository={repo}"])
    args.extend(
        [
            "-f",
            f"pr_number={pr['number']}",
            "-f",
            f"pr_base_ref={pr['baseRefName']}",
            "-f",
            f"pr_base_sha={pr['baseRefOid']}",
            "-f",
            f"pr_head_ref={pr['headRefName']}",
            "-f",
            f"pr_head_sha={pr['headRefOid']}",
        ]
    )
    if dry_run:
        print("DRY-RUN:", " ".join(args))
        return
    run(args)


def inspect_pr(
    repo: str,
    pr: dict[str, Any],
    args: argparse.Namespace,
    *,
    comments: list[dict[str, Any]] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Inspect one PR and optionally dispatch autofix."""
    number = int(pr["number"])
    if pr.get("isDraft"):
        return "skip", ("draft PR",)
    if pr.get("baseRefName") != args.base_branch:
        return "skip", (f"base branch is {pr.get('baseRefName')}; expected {args.base_branch}",)
    if not same_repository_head(repo, pr):
        return "skip", ("external PR head is not writable by repository workflow credentials",)

    needs_fix, reasons = needs_autofix(pr)
    if not needs_fix:
        return "skip", ("no current-head change request or active unresolved review thread",)

    if comments is None:
        comments = issue_comments(repo, number)

    if recent_fix_marker_exists(comments, str(pr["headRefOid"]), args.retry_hours * 3600):
        return "wait", ("recent autofix marker exists for this head",)

    dispatch_autofix(
        repo,
        pr,
        workflow=args.autofix_workflow,
        workflow_repository=args.autofix_repository,
        dry_run=args.dry_run,
    )
    create_fix_marker(repo, pr, dry_run=args.dry_run)
    return "dispatch", reasons


def process_queue(args: argparse.Namespace) -> int:
    """Inspect open PRs and dispatch bounded autofix work."""
    prs = fetch_pr(args.repo, args.pr_number) if args.pr_number else fetch_open_prs(args.repo, args.max_prs)
    dispatched = 0
    inspected = 0
    decisions: list[dict[str, Any]] = []

    prs_needing_comments = []
    for pr in prs:
        if pr.get("isDraft"):
            continue
        if pr.get("baseRefName") != args.base_branch:
            continue
        if not same_repository_head(args.repo, pr):
            continue
        needs_fix, _ = needs_autofix(pr)
        if needs_fix:
            prs_needing_comments.append(pr)

    comments_by_pr: dict[int, list[dict[str, Any]]] = {}
    if len(prs_needing_comments) <= 1:
        # Fast path for single items
        for pr in prs_needing_comments:
            pr_number = int(pr["number"])
            comments_by_pr[pr_number] = issue_comments(args.repo, pr_number)
    else:
        # ⚡ Bolt: Avoid N+1 API blocking by parallelizing independent issue_comments fetches
        # Impact: Reduces wait time from O(N) API calls to O(N/max_workers) for queue scanning
        max_workers = min(10, len(prs_needing_comments))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            def fetch_comments(pr_number: int) -> tuple[int, list[dict[str, Any]]]:
                """Fetch one PR's issue comments for parallel queue inspection."""
                return pr_number, issue_comments(args.repo, pr_number)

            futures = [executor.submit(fetch_comments, int(pr["number"])) for pr in prs_needing_comments]
            for future in concurrent.futures.as_completed(futures):
                try:
                    pr_number, comments = future.result()
                    comments_by_pr[pr_number] = comments
                except Exception:
                    pass

    for pr in prs:
        inspected += 1
        if dispatched >= args.max_dispatches:
            decisions.append({"pr": pr["number"], "action": "skip", "reasons": ["autofix dispatch limit reached"]})
            continue
        try:
            pr_number = int(pr["number"])
            action, reasons = inspect_pr(
                args.repo,
                pr,
                args,
                comments=comments_by_pr.get(pr_number),
            )
        except RuntimeError as exc:
            action, reasons = "error", (str(exc),)
        if action == "dispatch":
            dispatched += 1
        decisions.append({"pr": pr["number"], "action": action, "reasons": list(reasons)})
        print(f"PR #{pr['number']}: {action}: {'; '.join(reasons)}")

    print(json.dumps({"inspected": inspected, "autofix_dispatches": dispatched, "decisions": decisions}))
    return 0


def self_test() -> int:
    """Run cheap contract checks."""
    head = "a" * 40
    comments = [{"body": f"{FIX_MARKER} head_sha={head} epoch={int(time.time())} -->"}]
    assert recent_fix_marker_exists(comments, head, 24 * 3600)
    assert not recent_fix_marker_exists(comments, "b" * 40, 24 * 3600)
    pr = {
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "Actionable source-backed finding with a suggested diff.",
                }
            ]
        },
        "reviewThreads": {"nodes": []},
        "headRefOid": head,
        "mergeStateStatus": "CLEAN",
    }
    assert needs_autofix(pr) == (True, ("current-head OpenCode requested changes",))
    dirty_pr = {**pr, "mergeStateStatus": "DIRTY"}
    assert needs_autofix(dirty_pr) == (False, ())
    model_exhausted_pr = {
        **pr,
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "OpenCode could not establish approval sufficiency because the model pool exhausted.",
                }
            ]
        },
    }
    assert needs_autofix(model_exhausted_pr) == (False, ())
    unresolved_thread_pr = {
        **pr,
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "OpenCode found unresolved reviewer or review-agent thread evidence before approval.",
                }
            ]
        },
    }
    assert needs_autofix(unresolved_thread_pr) == (False, ())
    print("self-test passed")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base-branch", default=os.environ.get("DEFAULT_BRANCH", ""))
    parser.add_argument("--pr-number", type=int, default=0)
    parser.add_argument("--max-prs", type=int, default=50)
    parser.add_argument("--max-dispatches", type=int, default=1)
    parser.add_argument("--retry-hours", type=int, default=24)
    parser.add_argument("--autofix-workflow", default="pr-review-autofix.yml")
    parser.add_argument(
        "--autofix-repository",
        default=os.environ.get("AUTOFIX_REPOSITORY", DEFAULT_AUTOFIX_REPOSITORY),
        help="Repository that owns the autofix workflow, in OWNER/NAME form.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return args
    if not args.repo:
        parser.error("--repo is required")
    if not REPO_RE.fullmatch(args.repo):
        parser.error("--repo must be in OWNER/NAME form")
    if not args.base_branch:
        parser.error("--base-branch is required")
    if args.pr_number < 0:
        parser.error("--pr-number must not be negative")
    if args.max_prs < 1:
        parser.error("--max-prs must be positive")
    if args.max_dispatches < 1:
        parser.error("--max-dispatches must be positive")
    if args.retry_hours < 1:
        parser.error("--retry-hours must be positive")
    if not REPO_RE.fullmatch(args.autofix_repository):
        parser.error("--autofix-repository must be in OWNER/NAME form")
    return args


def main(argv: list[str]) -> int:
    """Run the fix scheduler CLI."""
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    return process_queue(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
