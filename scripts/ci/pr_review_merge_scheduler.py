#!/usr/bin/env python3
"""Inspect PR review state and drive centralized OpenCode merge automation."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any


OPEN_PRS_QUERY = """\
query($owner: String!, $name: String!, $pageSize: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: $pageSize, after: $cursor, states: OPEN, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number
        title
        isDraft
        mergeable
        mergeStateStatus
        reviewDecision
        baseRefName
        baseRefOid
        headRefName
        headRefOid
        headRepository { nameWithOwner }
        autoMergeRequest { enabledAt }
        reviewThreads(first: 100) {
          nodes { isResolved isOutdated }
        }
        reviews(last: 50) {
          nodes {
            state
            body
            submittedAt
            author { login }
            commit { oid }
          }
        }
        statusCheckRollup {
          contexts(first: 100) {
            nodes {
              __typename
              ... on CheckRun {
                name
                status
                conclusion
                checkSuite {
                  workflowRun {
                    workflow { name }
                  }
                }
              }
              ... on StatusContext {
                context
                state
              }
            }
          }
        }
      }
    }
  }
}
"""


@dataclass
class Decision:
    """Scheduler decision for a single pull request."""

    pr: int
    action: str
    reason: str


def run(args: Sequence[str], *, stdin: str | None = None) -> str:
    """Run a command and return stdout, raising with stderr on failure."""
    if isinstance(args, str) or not all(isinstance(arg, str) for arg in args):
        raise TypeError("run() requires a sequence of argv strings; shell command strings are not allowed")
    argv = list(args)
    process = subprocess.run(argv, input=stdin, capture_output=True, text=True, shell=False)
    if process.returncode != 0:
        raise RuntimeError(
            f"Command failed ({process.returncode}): {' '.join(argv)}\n{process.stderr}"
        )
    return process.stdout


def split_repo(repo: str) -> tuple[str, str]:
    """Split an owner/name repository string into owner and repository name."""
    try:
        owner, name = repo.split("/", 1)
    except ValueError as exc:
        raise ValueError(f"repo must be owner/name, got {repo!r}") from exc
    if not owner or not name:
        raise ValueError(f"repo must be owner/name, got {repo!r}")
    return owner, name


def gh_graphql(query: str, **fields: str | int) -> dict[str, Any]:
    """Run a GitHub GraphQL query through gh and decode the JSON response."""
    cmd = ["gh", "api", "graphql", "-F", "query=@-"]
    for key, value in fields.items():
        flag = "-F" if isinstance(value, int) else "-f"
        cmd.extend([flag, f"{key}={value}"])
    return json.loads(run(cmd, stdin=query))


def fetch_open_prs(repo: str, max_prs: int) -> list[dict[str, Any]]:
    """Fetch open pull requests from GitHub, paginating up to max_prs."""
    owner, name = split_repo(repo)
    prs: list[dict[str, Any]] = []
    cursor: str | None = None

    while len(prs) < max_prs:
        page_size = min(100, max_prs - len(prs))
        fields: dict[str, str | int] = {
            "owner": owner,
            "name": name,
            "pageSize": page_size,
        }
        if cursor:
            fields["cursor"] = cursor
        payload = gh_graphql(OPEN_PRS_QUERY, **fields)
        pr_page = payload["data"]["repository"]["pullRequests"]
        prs.extend(pr_page.get("nodes") or [])
        if not pr_page["pageInfo"]["hasNextPage"]:
            break
        cursor = pr_page["pageInfo"]["endCursor"]

    return prs


def context_nodes(pr: dict[str, Any]) -> list[dict[str, Any]]:
    """Return status rollup context nodes for a pull request payload."""
    rollup = pr.get("statusCheckRollup") or {}
    contexts = rollup.get("contexts") or {}
    return contexts.get("nodes") or []


def is_opencode_context(node: dict[str, Any]) -> bool:
    """Return whether a check or status context belongs to OpenCode Review."""
    if node.get("__typename") == "CheckRun":
        workflow = (
            ((node.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow")
            or {}
        )
        return node.get("name") == "opencode-review" or workflow.get("name") == "OpenCode Review"
    return node.get("context") == "opencode-review"


def is_strix_context(node: dict[str, Any]) -> bool:
    """Return whether a check or status context belongs to Strix evidence."""
    if node.get("__typename") == "CheckRun":
        workflow = (
            ((node.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow")
            or {}
        )
        workflow_name = workflow.get("name")
        return workflow_name in {"Strix Security Scan", "Strix"} or (
            node.get("name") == "strix" and workflow_name is None
        )
    return (node.get("context") or "") in {"strix", "Strix Security Scan"}


def opencode_in_progress(pr: dict[str, Any]) -> bool:
    """Return whether any OpenCode review status for the PR is still running."""
    for node in context_nodes(pr):
        if not is_opencode_context(node):
            continue
        status = (node.get("status") or node.get("state") or "").upper()
        if status and status not in {"COMPLETED", "SUCCESS", "FAILURE", "ERROR"}:
            return True
    return False


def strix_evidence_state(pr: dict[str, Any]) -> str:
    """Return missing, running, or complete for current-head Strix evidence."""
    found = False
    for node in context_nodes(pr):
        if not is_strix_context(node):
            continue
        found = True
        status = (node.get("status") or node.get("state") or "").upper()
        if status in {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}:
            return "running"
        if node.get("__typename") == "CheckRun" and status != "COMPLETED":
            return "running"
    return "complete" if found else "missing"


def unresolved_thread_count(pr: dict[str, Any]) -> int:
    """Count active, non-outdated unresolved review threads on a PR."""
    threads = ((pr.get("reviewThreads") or {}).get("nodes") or [])
    return sum(1 for thread in threads if not thread.get("isResolved") and not thread.get("isOutdated"))


def review_author_login(review: dict[str, Any]) -> str:
    """Return a normalized review author login."""
    return ((review.get("author") or {}).get("login") or "").lower()


def is_opencode_review(review: dict[str, Any]) -> bool:
    """Return whether a review was authored by the OpenCode agent."""
    return review_author_login(review) in {"opencode-agent", "opencode-agent[bot]"}


def current_head_review_state(pr: dict[str, Any], state: str) -> bool:
    """Return whether OpenCode's latest current-head review has the target state."""
    head = pr.get("headRefOid")
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if not is_opencode_review(review):
            continue
        commit = (review.get("commit") or {}).get("oid")
        if commit != head:
            continue
        return (review.get("state") or "").upper() == state
    return False


def has_current_head_approval(pr: dict[str, Any]) -> bool:
    """Return whether OpenCode approved the exact current head commit."""
    return current_head_review_state(pr, "APPROVED")


def has_current_head_changes_requested(pr: dict[str, Any]) -> bool:
    """Return whether OpenCode requested changes on the exact current head."""
    return current_head_review_state(pr, "CHANGES_REQUESTED")


def failed_status_checks(pr: dict[str, Any]) -> list[str]:
    """Return failing check or status context names from the PR rollup."""
    failed: list[str] = []
    successful_status_contexts = {
        node.get("context")
        for node in context_nodes(pr)
        if node.get("__typename") != "CheckRun"
        and (node.get("state") or "").upper() == "SUCCESS"
    }
    for node in context_nodes(pr):
        if node.get("__typename") == "CheckRun":
            conclusion = (node.get("conclusion") or "").upper()
            if conclusion in {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}:
                if is_strix_context(node) and "strix" in successful_status_contexts:
                    continue
                failed.append(node.get("name") or "check-run")
        else:
            state = (node.get("state") or "").upper()
            if state in {"FAILURE", "ERROR"}:
                failed.append(node.get("context") or "status-context")
    return failed


def enable_auto_merge(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Enable merge-commit auto-merge for a PR at its current head."""
    number = str(pr["number"])
    head = pr["headRefOid"]
    if dry_run:
        return
    run(["gh", "pr", "merge", number, "--repo", repo, "--auto", "--merge", "--match-head-commit", head])


def update_branch(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Ask GitHub to update a PR branch, guarded by the observed head SHA."""
    number = str(pr["number"])
    head = pr["headRefOid"]
    if dry_run:
        return
    run(
        [
            "gh",
            "api",
            "-X",
            "PUT",
            f"repos/{repo}/pulls/{number}/update-branch",
            "-f",
            f"expected_head_sha={head}",
        ]
    )


def dispatch_opencode_review(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Dispatch the OpenCode Review workflow for the PR head."""
    if dry_run:
        return
    run(
        [
            "gh",
            "workflow",
            "run",
            workflow,
            "--repo",
            repo,
            "--ref",
            pr["baseRefName"],
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


def dispatch_strix_evidence(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Dispatch same-head Strix workflow evidence before OpenCode reviews."""
    if dry_run:
        return
    run(
        [
            "gh",
            "workflow",
            "run",
            workflow,
            "--repo",
            repo,
            "--ref",
            pr["baseRefName"],
            "-f",
            f"pr_number={pr['number']}",
            "-f",
            f"pr_base_sha={pr['baseRefOid']}",
            "-f",
            f"pr_head_sha={pr['headRefOid']}",
        ]
    )


def inspect_pr(
    repo: str,
    pr: dict[str, Any],
    *,
    dry_run: bool,
    trigger_reviews: bool,
    enable_auto_merge_flag: bool,
    update_branches: bool,
    workflow: str,
    security_workflow: str,
    base_branch: str,
) -> Decision:
    """Decide and optionally act on one pull request's merge-readiness state."""
    number = pr["number"]
    head_repo = (pr.get("headRepository") or {}).get("nameWithOwner")
    base_ref = pr.get("baseRefName")

    if pr.get("isDraft"):
        return Decision(number, "skip", "draft PR")
    if base_ref != base_branch:
        return Decision(number, "skip", f"base branch is {base_ref}; expected {base_branch}")
    if head_repo != repo:
        return Decision(number, "skip", f"fork or external head repo: {head_repo}")

    merge_state = (pr.get("mergeStateStatus") or "").upper()
    if merge_state in {"DIRTY", "CONFLICTING"}:
        return Decision(number, "block", f"merge conflict: {merge_state}")

    unresolved = unresolved_thread_count(pr)
    if unresolved:
        return Decision(number, "block", f"{unresolved} unresolved review thread(s)")

    if has_current_head_changes_requested(pr):
        return Decision(number, "block", "current-head OpenCode review requested changes")

    if merge_state == "BEHIND" and has_current_head_approval(pr):
        if not update_branches:
            return Decision(number, "wait", "current-head OpenCode review approved; branch update disabled")
        update_branch(repo, pr, dry_run=dry_run)
        return Decision(number, "update_branch", "current-head OpenCode review approved; branch update requested")

    if has_current_head_approval(pr):
        failed_checks = failed_status_checks(pr)
        if failed_checks:
            return Decision(number, "block", f"failed check(s): {', '.join(failed_checks[:5])}")
        if pr.get("autoMergeRequest"):
            return Decision(number, "wait", "current head is approved; auto-merge already enabled")
        if not enable_auto_merge_flag:
            return Decision(number, "wait", "current head is approved; auto-merge disabled by scheduler inputs")
        enable_auto_merge(repo, pr, dry_run=dry_run)
        return Decision(number, "auto_merge", "current head is approved; auto-merge enabled")

    if opencode_in_progress(pr):
        return Decision(number, "wait", "OpenCode review is already in progress")

    if trigger_reviews:
        strix_state = strix_evidence_state(pr)
        if strix_state == "missing":
            dispatch_strix_evidence(repo, security_workflow, pr, dry_run=dry_run)
            return Decision(
                number,
                "security_dispatch",
                "current head has no completed Strix evidence; same-head Strix dispatched",
            )
        if strix_state == "running":
            return Decision(number, "wait", "same-head Strix evidence is still running")
        # Legacy trusted-base Strix self-test sentinel while this scheduler rollout lands:
        # same-head Strix and OpenCode dispatched
        dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
        return Decision(
            number,
            "review_dispatch",
            "current head has completed Strix evidence; same-head OpenCode dispatched",
        )

    return Decision(number, "block", "current head has no OpenCode approval")


def print_summary(
    decisions: list[Decision],
    *,
    dry_run: bool,
    base_branch: str,
    project_flow: str,
) -> None:
    """Print human-readable and machine-readable scheduler decisions."""
    counts: dict[str, int] = {}
    for decision in decisions:
        counts[decision.action] = counts.get(decision.action, 0) + 1
        print(f"PR #{decision.pr}: {decision.action}: {decision.reason}")
    print(
        json.dumps(
            {
                "base_branch": base_branch,
                "dry_run": dry_run,
                "inspected": len(decisions),
                "counts": counts,
                "project_flow": project_flow,
            },
            sort_keys=True,
        )
    )


def summarize_action_error(exc: RuntimeError) -> str:
    """Return a compact, log-safe scheduler action error summary."""
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    if not lines:
        return "scheduler action failed without stderr"
    return "; ".join(lines[:2])[:500]


def self_test() -> None:
    """Exercise scheduler invariants without GitHub network access."""
    sample = {
        "number": 1,
        "headRefOid": "abc",
        "baseRefName": "main",
        "baseRefOid": "base",
        "headRefName": "feature",
        "mergeStateStatus": "CLEAN",
        "isDraft": False,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "reviewDecision": "REVIEW_REQUIRED",
        "reviewThreads": {"nodes": []},
        "reviews": {
            "nodes": [
                {
                    "state": "APPROVED",
                    "author": {"login": "opencode-agent"},
                    "body": "OpenCode Agent approved this head.",
                    "commit": {"oid": "abc"},
                }
            ]
        },
        "statusCheckRollup": {"contexts": {"nodes": []}},
    }
    assert has_current_head_approval(sample)
    assert not has_current_head_changes_requested(sample)
    decision = inspect_pr(
        "owner/repo",
        sample,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    assert decision.action == "auto_merge"
    sample["statusCheckRollup"]["contexts"]["nodes"] = [
        {"__typename": "CheckRun", "name": "strix", "status": "COMPLETED", "conclusion": "FAILURE"}
    ]
    decision = inspect_pr(
        "owner/repo",
        sample,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    assert decision.action == "block"
    assert "strix" in decision.reason
    sample["statusCheckRollup"]["contexts"]["nodes"] = []
    sample["reviews"]["nodes"].append(
        {
            "state": "APPROVED",
            "author": {"login": "not-opencode-agent"},
            "body": "OpenCode Agent approved this head.",
            "commit": {"oid": "abc"},
        }
    )
    assert has_current_head_approval(sample)
    sample["reviews"]["nodes"] = [sample["reviews"]["nodes"][-1]]
    assert not has_current_head_approval(sample)
    sample["reviews"]["nodes"].append(
        {
            "state": "CHANGES_REQUESTED",
            "author": {"login": "opencode-agent"},
            "commit": {"oid": "old"},
        }
    )
    assert not has_current_head_changes_requested(sample)
    sample["statusCheckRollup"]["contexts"]["nodes"].append(
        {"__typename": "CheckRun", "name": "opencode-review", "status": "IN_PROGRESS"}
    )
    assert opencode_in_progress(sample)
    sample["statusCheckRollup"]["contexts"]["nodes"] = []
    sample["mergeStateStatus"] = "BEHIND"
    sample["reviews"]["nodes"] = [
        {
            "state": "APPROVED",
            "author": {"login": "opencode-agent"},
            "commit": {"oid": "old"},
        }
    ]
    decision = inspect_pr(
        "owner/repo",
        sample,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    assert decision.action == "security_dispatch"
    sample["statusCheckRollup"]["contexts"]["nodes"] = [
        {
            "__typename": "CheckRun",
            "name": "strix",
            "status": "COMPLETED",
            "conclusion": "SUCCESS",
            "checkSuite": {"workflowRun": {"workflow": {"name": "Strix Security Scan"}}},
        }
    ]
    decision = inspect_pr(
        "owner/repo",
        sample,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    assert decision.action == "review_dispatch"
    sample["reviews"]["nodes"][0]["commit"]["oid"] = "abc"
    decision = inspect_pr(
        "owner/repo",
        sample,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    assert decision.action == "update_branch"
    print("self-test passed")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse scheduler CLI arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base-branch", default=os.environ.get("DEFAULT_BRANCH", ""))
    parser.add_argument("--project-flow", default=os.environ.get("PROJECT_FLOW", ""))
    parser.add_argument("--max-prs", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--trigger-reviews", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-auto-merge", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--update-branches", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--review-workflow", default="OpenCode Review")
    parser.add_argument("--security-workflow", default="Strix Security Scan")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the scheduler CLI."""
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if not args.repo:
        raise SystemExit("--repo is required")
    if not args.base_branch:
        raise SystemExit("--base-branch is required")
    if not args.project_flow:
        raise SystemExit("--project-flow is required")
    prs = fetch_open_prs(args.repo, args.max_prs)
    decisions = []
    for pr in prs:
        try:
            decision = inspect_pr(
                args.repo,
                pr,
                dry_run=args.dry_run,
                trigger_reviews=args.trigger_reviews,
                enable_auto_merge_flag=args.enable_auto_merge,
                update_branches=args.update_branches,
                workflow=args.review_workflow,
                security_workflow=args.security_workflow,
                base_branch=args.base_branch,
            )
        except RuntimeError as exc:
            decision = Decision(
                pr.get("number", 0),
                "action_error",
                summarize_action_error(exc),
            )
        decisions.append(decision)
    print_summary(
        decisions,
        dry_run=args.dry_run,
        base_branch=args.base_branch,
        project_flow=args.project_flow,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main(sys.argv[1:]))
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
