#!/usr/bin/env python3
"""Dispatch conservative PR repair runs for actionable exact-head evidence."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from typing import Any

try:
    from pr_review_merge_scheduler import (
        complete_paginated_pr_contexts,
        fetch_open_prs,
        fetch_pr,
        force_cancel_workflow_runs,
        context_nodes,
        has_current_head_approval,
        has_current_head_changes_requested,
        is_opencode_review,
        latest_check_run_attempts,
        REST_UNKNOWN_GITHUB_ACTIONS_WORKFLOW,
        review_matches_current_head,
        run,
        unresolved_thread_count,
    )
except ModuleNotFoundError:
    from scripts.ci.pr_review_merge_scheduler import (
        complete_paginated_pr_contexts,
        fetch_open_prs,
        fetch_pr,
        force_cancel_workflow_runs,
        context_nodes,
        has_current_head_approval,
        has_current_head_changes_requested,
        is_opencode_review,
        latest_check_run_attempts,
        REST_UNKNOWN_GITHUB_ACTIONS_WORKFLOW,
        review_matches_current_head,
        run,
        unresolved_thread_count,
    )


DEFAULT_AUTOFIX_REPOSITORY = "ContextualWisdomLab/.github"
DEFAULT_AUTOFIX_WORKFLOW = "pr-review-autofix.yml"
AUTOFIX_REPOSITORY_DISPATCH_TYPE = "pr-review-autofix"
FIX_MARKER = "<!-- pr-review-fix-scheduler autofix-dispatch"
FIX_MARKER_RE = re.compile(
    r"<!-- pr-review-fix-scheduler autofix-dispatch "
    r"head_sha=([0-9a-fA-F]{40}) epoch=([0-9]+) -->"
)
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REPAIR_MODES = frozenset({"review", "rca", "conflict"})
AUTOFIX_RUN_NAME_RE = re.compile(
    r"^PR Review Autofix (?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)"
    r"#(?P<pr>[1-9][0-9]*)@(?P<head>[0-9a-fA-F]{40})$"
)
ACTIVE_RUN_STATUSES = frozenset({"queued", "in_progress", "pending", "requested", "waiting"})
NON_AUTOFIX_CHANGE_REQUEST_MARKERS = (
    "merge conflict",
    "mergestatestatus `dirty`",
    "mergestatestatus dirty",
    "model pool exhausted",
    "could not establish approval sufficiency",
    "independent approval",
    "unresolved human review thread",
    "unresolved reviewer thread",
    "unresolved reviewer or review-agent thread",
    "queued check",
    "pending check",
    "check rollup cannot be verified",
)
RCA_REPAIR_CHANGE_REQUEST_MARKERS = (
    "failed check",
    "failed-check",
    "coverage-evidence",
    "strix failed",
    "security scan failed",
    "sast semgrep failed",
    "codeql failed",
)
RCA_IGNORED_CHECK_NAMES = frozenset(
    {
        "metadata-only gate evaluation",
        "opencode-review",
        "PR governance metadata controller",
        "scan-pr-queue",
    }
)
RCA_IGNORED_WORKFLOW_NAMES = frozenset(
    {
        "OpenCode Review",
        "Required OpenCode Review",
        "OpenCode PR Review",
        REST_UNKNOWN_GITHUB_ACTIONS_WORKFLOW,
    }
)
FAILED_CHECK_CONCLUSIONS = frozenset(
    {"FAILURE", "STARTUP_FAILURE", "TIMED_OUT"}
)
FAILED_STATUS_STATES = frozenset({"ERROR", "FAILURE"})


def run_json(args: list[str]) -> Any:
    """Run gh and decode JSON."""
    return json.loads(run(["gh", *args]) or "null")


def live_head_matches(repo: str, pr: dict[str, Any]) -> bool:
    """Return whether GitHub still reports the scheduler's exact PR head."""
    payload = run_json(["api", f"repos/{repo}/pulls/{int(pr['number'])}"])
    if not isinstance(payload, dict) or not isinstance(payload.get("head"), dict):
        return False
    live_head = payload["head"].get("sha")
    expected_head = str(pr.get("headRefOid") or "")
    return (
        isinstance(live_head, str)
        and len(live_head) == 40
        and live_head.lower() == expected_head.lower()
    )


RATE_LIMIT_ERROR_MARKERS = ("api rate limit exceeded", "secondary rate limit")
ISSUE_COMMENTS_RETRY_ATTEMPTS = 2
ISSUE_COMMENTS_RETRY_BACKOFF_SECONDS = 15


def is_rate_limit_error(exc: BaseException) -> bool:
    """Return whether an exception's message names a GitHub API rate limit."""
    message = str(exc).lower()
    return any(marker in message for marker in RATE_LIMIT_ERROR_MARKERS)


def issue_comments(repo: str, number: int) -> list[dict[str, Any]]:
    """Return issue comments for a PR, retrying transient rate-limit errors.

    The shared OpenCode app installation's API budget is contended by many
    concurrent org-wide scheduled workflows, so a rate-limit error here is
    often transient. Retry it with a short linear backoff up to
    ISSUE_COMMENTS_RETRY_ATTEMPTS times before propagating; any other error,
    or a rate-limit error past the retry budget, propagates immediately.
    ``per_page=100`` bounds the paginated request count for PRs with a long
    review-comment history. ``-X GET`` is explicit and required: ``gh api``
    defaults to POST once any ``-f``/``-F`` field is present unless
    ``-X``/``--method`` overrides it, and a POST against this endpoint with
    no ``body`` field fails every call outright.
    """
    attempt = 0
    while True:
        try:
            pages = run_json(
                [
                    "api",
                    f"repos/{repo}/issues/{number}/comments",
                    "--paginate",
                    "--slurp",
                    "-X",
                    "GET",
                    "-f",
                    "per_page=100",
                ]
            )
            return [comment for page in pages for comment in page]
        except RuntimeError as exc:
            if attempt >= ISSUE_COMMENTS_RETRY_ATTEMPTS or not is_rate_limit_error(exc):
                raise
            attempt += 1
            time.sleep(ISSUE_COMMENTS_RETRY_BACKOFF_SECONDS * attempt)


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
    """Return whether repository workflow credentials can mutate the PR head."""
    return ((pr.get("headRepository") or {}).get("nameWithOwner") or "") == repo


def latest_current_head_opencode_review(pr: dict[str, Any]) -> dict[str, Any] | None:
    """Return the newest OpenCode review for the current head, if present."""
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if is_opencode_review(review) and review_matches_current_head(review, pr):
            return review
    return None


def _clean_change_request_body(pr: dict[str, Any]) -> str | None:
    """Return normalized exact-head OpenCode review text for a clean PR."""
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if merge_state not in {"CLEAN", "HAS_HOOKS"}:
        return None
    review = latest_current_head_opencode_review(pr)
    if review is None:
        return None
    return str(review.get("body") or "").lower()


def change_request_is_autofixable(pr: dict[str, Any]) -> bool:
    """Return whether ordinary review feedback is safe for bounded autofix."""
    body = _clean_change_request_body(pr)
    if body is None:
        return False
    if any(marker in body for marker in NON_AUTOFIX_CHANGE_REQUEST_MARKERS):
        return False
    if any(marker in body for marker in RCA_REPAIR_CHANGE_REQUEST_MARKERS):
        return False
    return True


def change_request_requires_rca(pr: dict[str, Any]) -> bool:
    """Return whether failed-check evidence warrants a bounded RCA repair run."""
    body = _clean_change_request_body(pr)
    if body is None:
        return False
    if any(marker in body for marker in NON_AUTOFIX_CHANGE_REQUEST_MARKERS):
        return False
    return any(marker in body for marker in RCA_REPAIR_CHANGE_REQUEST_MARKERS)


def needs_autofix(pr: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return whether current-head evidence justifies ordinary review autofix."""
    reasons: list[str] = []
    if not (
        has_current_head_changes_requested(pr)
        and change_request_is_autofixable(pr)
    ):
        return False, ()

    reasons.append("current-head OpenCode requested changes")
    unresolved = unresolved_thread_count(pr)
    if unresolved:
        reasons.append(f"{unresolved} active unresolved review thread(s)")
    return bool(reasons), tuple(reasons)


def needs_rca_repair(pr: dict[str, Any]) -> tuple[bool, tuple[str, ...]]:
    """Return whether exact-head failed-check evidence warrants RCA and repair."""
    review_requires_rca = (
        has_current_head_changes_requested(pr)
        and change_request_requires_rca(pr)
    )
    failed_checks = current_head_failed_checks(pr)
    if not review_requires_rca and not failed_checks:
        return False, ()
    if failed_checks:
        return True, (
            "current-head failed check(s) require RCA: " + ", ".join(failed_checks),
        )
    return True, ("current-head failed-check blocker requires RCA",)


def current_head_failed_checks(pr: dict[str, Any]) -> tuple[str, ...]:
    """Return terminal failed checks that can carry source-backed RCA evidence."""
    failed: list[str] = []
    rollup = pr.get("statusCheckRollup") or {}
    nodes = rollup if isinstance(rollup, list) else context_nodes(pr)
    for node in latest_check_run_attempts(nodes):
        if node.get("__typename") == "CheckRun":
            name = str(node.get("name") or "").strip()
            workflow_name = str(
                (
                    ((node.get("checkSuite") or {}).get("workflowRun") or {}).get(
                        "workflow"
                    )
                    or {}
                ).get("name")
                or ""
            ).strip()
            conclusion = str(node.get("conclusion") or "").upper()
            if (
                name not in RCA_IGNORED_CHECK_NAMES
                and workflow_name not in RCA_IGNORED_WORKFLOW_NAMES
                and conclusion in FAILED_CHECK_CONCLUSIONS
            ):
                failed.append(name or "unnamed check")
        else:
            name = str(node.get("context") or "").strip()
            state = str(node.get("state") or "").upper()
            if name not in RCA_IGNORED_CHECK_NAMES and state in FAILED_STATUS_STATES:
                failed.append(name or "unnamed status")
    return tuple(dict.fromkeys(failed))


CONFLICT_MERGE_STATES = frozenset({"DIRTY", "CONFLICTING"})


def needs_conflict_resolution(
    pr: dict[str, Any],
    *,
    allow_unreviewed: bool = False,
) -> tuple[bool, tuple[str, ...]]:
    """Return whether a GitHub-reported conflict is safe to auto-resolve.

    Direct library callers retain the historical current-head approval
    prerequisite unless ``allow_unreviewed`` is explicit. Trusted scheduled
    callers enable it because conflict repair creates a new head and therefore
    requires fresh reviews and checks regardless of the previous review state.
    """
    merge_state = str(pr.get("mergeStateStatus") or "").upper()
    if merge_state not in CONFLICT_MERGE_STATES:
        return False, ()
    approved = has_current_head_approval(pr)
    if not approved and not allow_unreviewed:
        return False, ()
    review_state = "current-head approved" if approved else "unreviewed"
    return True, (
        f"{review_state} PR is {merge_state.lower()}; auto-resolving the merge "
        "conflict and requiring fresh review and checks on the resulting head",
    )


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
    resolve_conflict: bool = False,
    repair_mode: str = "review",
) -> None:
    """Dispatch a repair worker for the exact PR head.

    ``repair_mode=rca`` tells the trusted context collector to gather failed
    check evidence and widen the sealed edit scope only to current PR files.
    ``resolve_conflict`` retains the separately bounded conflict path.
    """
    dispatch_repo = workflow_repository or repo
    if workflow != DEFAULT_AUTOFIX_WORKFLOW:
        raise ValueError(
            f"autofix workflow must be {DEFAULT_AUTOFIX_WORKFLOW!r}; got {workflow!r}"
        )
    if not REPO_RE.fullmatch(dispatch_repo):
        raise ValueError(f"invalid autofix workflow repository: {dispatch_repo!r}")
    effective_mode = "conflict" if resolve_conflict else repair_mode
    if effective_mode not in REPAIR_MODES:
        raise ValueError(f"invalid repair mode: {effective_mode!r}")
    payload = {
        "event_type": AUTOFIX_REPOSITORY_DISPATCH_TYPE,
        "client_payload": {
            "target_repository": repo,
            "pr_number": int(pr["number"]),
            "pr_base_ref": pr["baseRefName"],
            "pr_base_sha": pr["baseRefOid"],
            "pr_head_ref": pr["headRefName"],
            "pr_head_sha": pr["headRefOid"],
            "resolve_conflict": "true" if resolve_conflict else "false",
            "repair_mode": effective_mode,
        },
    }
    args = [
        "gh",
        "api",
        "-X",
        "POST",
        f"repos/{dispatch_repo}/dispatches",
        "--input",
        "-",
    ]
    if dry_run:
        print("DRY-RUN:", " ".join(args), json.dumps(payload, sort_keys=True))
        return
    if not live_head_matches(repo, pr):
        raise RuntimeError("pull request live head changed before autofix dispatch")
    run(args, stdin=json.dumps(payload))


def prepare_autofix_slot(
    repo: str,
    pr: dict[str, Any],
    *,
    workflow: str,
    workflow_repository: str,
    dry_run: bool,
) -> bool | None:
    """Cancel older-head workers; return ``None`` when this PR snapshot went stale."""
    dispatch_repo = workflow_repository or repo
    payload = run_json(
        [
            "api",
            f"repos/{dispatch_repo}/actions/workflows/{workflow}/runs",
            "-X",
            "GET",
            "-f",
            "event=repository_dispatch",
            "-f",
            "per_page=100",
            "--paginate",
            "--slurp",
        ]
    )
    number = int(pr["number"])
    head = str(pr["headRefOid"]).lower()
    same_head = False
    stale_ids: list[str] = []
    pages = payload if isinstance(payload, list) else [payload]
    for workflow_run in (
        workflow_run
        for page in pages
        for workflow_run in page.get("workflow_runs", [])
    ):
        if str(workflow_run.get("status") or "") not in ACTIVE_RUN_STATUSES:
            continue
        match = AUTOFIX_RUN_NAME_RE.fullmatch(
            str(workflow_run.get("display_title") or "")
        )
        if not match or match.group("repo") != repo or int(match.group("pr")) != number:
            continue
        if match.group("head").lower() == head:
            same_head = True
        else:
            stale_ids.append(str(workflow_run["id"]))
    if stale_ids:
        if dry_run:
            print(f"DRY-RUN: would force-cancel stale autofix runs {', '.join(stale_ids)}")
        elif not live_head_matches(repo, pr):
            return None
        else:
            force_cancel_workflow_runs(dispatch_repo, stale_ids)
    return same_head


def _base_branch_matches(pr: dict[str, Any], expected: str) -> bool:
    """Return whether a PR belongs to the configured base scope."""
    return expected == "*" or pr.get("baseRefName") == expected


def inspect_pr(
    repo: str,
    pr: dict[str, Any],
    args: argparse.Namespace,
    *,
    comments: list[dict[str, Any]] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """Inspect one PR and optionally dispatch a bounded repair."""
    number = int(pr["number"])
    if not _base_branch_matches(pr, args.base_branch):
        return "skip", (
            f"base branch is {pr.get('baseRefName')}; expected {args.base_branch}",
        )
    if not same_repository_head(repo, pr):
        return "skip", (
            "external PR head is not writable by repository workflow credentials",
        )

    conflicted = str(pr.get("mergeStateStatus") or "").upper() in CONFLICT_MERGE_STATES
    if conflicted:
        if pr.get("isDraft"):
            return "skip", ("draft PR",)
        needs_resolve, resolve_reasons = needs_conflict_resolution(
            pr,
            allow_unreviewed=bool(
                getattr(args, "resolve_unreviewed_conflicts", False)
            ),
        )
        if not needs_resolve:
            return "skip", ("merge conflict is not authorized for repair",)
        needs_fix = True
        reasons = resolve_reasons
        repair_mode = "conflict"
        resolve_conflict = True
    else:
        needs_fix, reasons = needs_autofix(pr)
        repair_mode = "review"
        resolve_conflict = False

    needs_rca, rca_reasons = needs_rca_repair(pr)
    if pr.get("isDraft") and not needs_rca:
        return "skip", ("draft PR",)

    if not conflicted and needs_rca:
        needs_fix = True
        repair_mode = "rca"
        reasons = rca_reasons
    elif not needs_fix and not conflicted:
        return "skip", (
            "no current-head autofixable review, failed-check RCA, or approved merge conflict",
        )

    if comments is None:
        try:
            comments = issue_comments(repo, number)
        except RuntimeError:
            return "wait", (
                "issue comment fetch failed; deferring to next scheduled pass",
            )

    if recent_fix_marker_exists(
        comments,
        str(pr["headRefOid"]),
        args.retry_hours * 3600,
    ):
        return "wait", ("recent autofix marker exists for this head",)

    slot_state = prepare_autofix_slot(
        repo,
        pr,
        workflow=args.autofix_workflow,
        workflow_repository=args.autofix_repository,
        dry_run=args.dry_run,
    )
    if slot_state is None:
        return "wait", ("scheduler PR snapshot is stale; retry with the current live head",)
    if slot_state:
        return "wait", ("current-head autofix run is already queued or running",)

    dispatch_kwargs: dict[str, Any] = {
        "workflow": args.autofix_workflow,
        "workflow_repository": args.autofix_repository,
        "dry_run": args.dry_run,
        "resolve_conflict": resolve_conflict,
    }
    if repair_mode == "rca":
        dispatch_kwargs["repair_mode"] = "rca"
    dispatch_autofix(repo, pr, **dispatch_kwargs)
    create_fix_marker(repo, pr, dry_run=args.dry_run)
    return "dispatch", reasons


def process_queue(args: argparse.Namespace) -> int:
    """Inspect open PRs and dispatch bounded repair work."""
    window_count = max(
        1,
        (args.max_prs + args.scan_window_size - 1) // args.scan_window_size,
    )
    window_offset = (args.rotation_seed % window_count) * args.scan_window_size
    prs = (
        fetch_pr(args.repo, args.pr_number)
        if args.pr_number
        else fetch_open_prs(
            args.repo,
            args.max_prs,
            offset=window_offset,
            window_size=args.scan_window_size,
        )
    )
    dispatched = 0
    inspected = 0
    decisions: list[dict[str, Any]] = []

    for pr in prs:
        if dispatched >= args.max_dispatches:
            break
        inspected += 1
        if _base_branch_matches(pr, args.base_branch) and same_repository_head(
            args.repo, pr
        ):
            try:
                complete_paginated_pr_contexts(args.repo, pr)
            except RuntimeError:
                reasons = (
                    "status-context pagination failed; deferring this PR without "
                    "evaluating partial check evidence",
                )
                decisions.append(
                    {"pr": pr["number"], "action": "wait", "reasons": list(reasons)}
                )
                print(f"PR #{pr['number']}: wait: {reasons[0]}")
                continue
        try:
            action, reasons = inspect_pr(args.repo, pr, args)
        except RuntimeError as exc:
            action, reasons = "error", (str(exc),)
        if action == "dispatch":
            dispatched += 1
        decisions.append(
            {
                "pr": pr["number"],
                "action": action,
                "reasons": list(reasons),
            }
        )
        print(f"PR #{pr['number']}: {action}: {'; '.join(reasons)}")

    print(
        json.dumps(
            {
                "inspected": inspected,
                "autofix_dispatches": dispatched,
                "decisions": decisions,
            }
        )
    )
    return 0


def self_test() -> int:
    """Run cheap contract checks."""
    head = "a" * 40
    comments = [
        {"body": f"{FIX_MARKER} head_sha={head} epoch={int(time.time())} -->"}
    ]
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
    assert needs_autofix(pr) == (
        True,
        ("current-head OpenCode requested changes",),
    )
    assert needs_rca_repair(pr) == (False, ())
    failed_check_pr = {
        **pr,
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "Failed check evidence shows coverage-evidence failed.",
                }
            ]
        },
    }
    assert needs_autofix(failed_check_pr) == (False, ())
    assert needs_rca_repair(failed_check_pr) == (
        True,
        ("current-head failed-check blocker requires RCA",),
    )
    dirty_pr = {**pr, "mergeStateStatus": "DIRTY"}
    assert needs_autofix(dirty_pr) == (False, ())
    assert needs_rca_repair(dirty_pr) == (False, ())
    approved_dirty_pr = {
        "reviews": {
            "nodes": [
                {
                    "state": "APPROVED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": "Approved.",
                }
            ]
        },
        "reviewThreads": {"nodes": []},
        "headRefOid": head,
        "mergeStateStatus": "DIRTY",
    }
    resolves, resolve_reasons = needs_conflict_resolution(approved_dirty_pr)
    assert resolves
    assert "auto-resolving" in resolve_reasons[0]
    assert needs_conflict_resolution(
        {**approved_dirty_pr, "mergeStateStatus": "CLEAN"}
    ) == (False, ())
    assert needs_conflict_resolution(dirty_pr) == (False, ())
    resolves, resolve_reasons = needs_conflict_resolution(
        dirty_pr,
        allow_unreviewed=True,
    )
    assert resolves
    assert "fresh review and checks" in resolve_reasons[0]
    model_exhausted_pr = {
        **pr,
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": (
                        "OpenCode could not establish approval sufficiency because "
                        "the model pool exhausted."
                    ),
                }
            ]
        },
    }
    assert needs_autofix(model_exhausted_pr) == (False, ())
    assert needs_rca_repair(model_exhausted_pr) == (False, ())
    unresolved_thread_pr = {
        **pr,
        "reviews": {
            "nodes": [
                {
                    "state": "CHANGES_REQUESTED",
                    "author": {"login": "opencode-agent"},
                    "commit": {"oid": head},
                    "body": (
                        "OpenCode found unresolved reviewer or review-agent thread "
                        "evidence before approval."
                    ),
                }
            ]
        },
    }
    assert needs_autofix(unresolved_thread_pr) == (False, ())
    assert needs_rca_repair(unresolved_thread_pr) == (False, ())
    print("self-test passed")
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base-branch", default=os.environ.get("DEFAULT_BRANCH", ""))
    parser.add_argument("--pr-number", type=int, default=0)
    parser.add_argument("--max-prs", type=int, default=50)
    parser.add_argument("--scan-window-size", type=int, default=50)
    parser.add_argument(
        "--rotation-seed",
        type=int,
        default=os.environ.get("GITHUB_RUN_NUMBER", "0"),
    )
    parser.add_argument("--max-dispatches", type=int, default=1)
    parser.add_argument("--retry-hours", type=int, default=24)
    parser.add_argument("--resolve-unreviewed-conflicts", action="store_true")
    parser.add_argument("--autofix-workflow", default="pr-review-autofix.yml")
    parser.add_argument(
        "--autofix-repository",
        default=os.environ.get(
            "AUTOFIX_REPOSITORY",
            DEFAULT_AUTOFIX_REPOSITORY,
        ),
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
    if args.scan_window_size < 1 or args.scan_window_size > 50:
        parser.error("--scan-window-size must be between 1 and 50")
    if args.rotation_seed < 0:
        parser.error("--rotation-seed must not be negative")
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
