#!/usr/bin/env python3
"""Inspect PR review state and drive centralized OpenCode merge automation."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
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
        commits(last: 1) {
          nodes {
            commit {
              oid
              authoredDate
              committedDate
            }
          }
        }
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
                startedAt
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

OPEN_PRS_PAGE_SIZE = 25
DEFAULT_STALE_OPENCODE_MINUTES = 45
RUNNING_CHECK_STATES = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}


@dataclass
class Decision:
    """Scheduler decision for a single pull request."""

    pr: int
    action: str
    reason: str


def contract_decision(decision: Decision) -> str:
    """Map scheduler actions into the bounded PR decision contract."""
    if decision.action == "update_branch":
        return "UPDATE_BRANCH"
    if decision.action in {"wait", "security_dispatch", "review_dispatch", "disable_auto_merge", "action_error"}:
        return "WAIT"
    if decision.action in {"skip", "auto_merge"}:
        return "NO_ACTION"
    if decision.action == "block" and "current-head OpenCode review requested changes" in decision.reason:
        return "REQUEST_CHANGES"
    return "WAIT"


def decision_payload(
    decisions: list[Decision],
    *,
    counts: dict[str, int],
    dry_run: bool,
    base_branch: str,
    project_flow: str,
) -> dict[str, Any]:
    """Return the machine-readable scheduler decision contract."""
    return {
        "schema_version": "pr-review-merge-scheduler/v1",
        "base_branch": base_branch,
        "dry_run": dry_run,
        "inspected": len(decisions),
        "counts": counts,
        "project_flow": project_flow,
        "decisions": [decision_contract_entry(decision) for decision in decisions],
    }


def decision_contract_entry(decision: Decision) -> dict[str, Any]:
    """Return one machine-readable decision contract entry."""
    entry: dict[str, Any] = {
        "pr": decision.pr,
        "action": decision.action,
        "contract_decision": contract_decision(decision),
        "reason": decision.reason,
    }
    guidance = decision_guidance(decision)
    if guidance:
        entry["guidance"] = guidance
    return entry


def decision_guidance(decision: Decision) -> dict[str, Any] | None:
    """Return actionable repair or automation guidance for known scheduler states."""
    parsed_conflict = parse_conflict_reason(decision.reason)
    if parsed_conflict:
        state, base_ref, head_ref = parsed_conflict
        base_remote = f"origin/{base_ref}"
        quoted_base_ref = shlex.quote(base_ref)
        quoted_base_remote = shlex.quote(base_remote)
        return {
            "type": "merge_conflict_repair",
            "merge_state": state,
            "base_ref": base_ref,
            "head_ref": head_ref,
            "summary": "Repair the PR branch against the latest base branch, then push the same branch so review and required checks rerun on the new head.",
            "automation_limit": "GitHub update-branch cannot choose merge-conflict resolutions; the scheduler must wait until the PR branch is repaired.",
            "steps": [
                "Check out the PR branch.",
                "Fetch the latest base branch.",
                "Choose merge or rebase; do not treat the conflict as an OpenCode finding.",
                "Resolve conflict markers in the PR branch and stage the resolved files.",
                "Run the focused checks for the changed area.",
                "Push the PR branch; use --force-with-lease only if the branch was rebased.",
            ],
            "commands": [
                f"gh pr checkout {decision.pr}",
                f"git fetch origin {quoted_base_ref}",
                f"git merge --no-ff {quoted_base_remote}",
                f"# or: git rebase {quoted_base_remote}",
                "git status --short",
                "git add <resolved-files>",
                "# merge path: git commit",
                "# rebase path: git rebase --continue",
                "git push",
                "# rebase path only: git push --force-with-lease",
            ],
        }
    if decision.action == "update_branch":
        return {
            "type": "github_actions_update_branch",
            "actor": "github-actions[bot]",
            "token": "workflow GITHUB_TOKEN",
            "required_permission": "pull-requests: write",
            "head_guard": "expected_head_sha",
            "summary": "GitHub Actions requests the PR branch update mechanically; the updated head must be reviewed again before merge.",
            "next_required_evidence": [
                "new head SHA after the update_branch mutation",
                "OpenCode approval on that exact new head",
                "same-head Strix evidence",
                "required GitHub Checks success",
                "zero active unresolved review threads",
            ],
        }
    if decision.action == "disable_auto_merge":
        return {
            "type": "fresh_head_review_required",
            "summary": "Auto-merge was disabled because the PR needs fresh same-head review evidence before it can be merged.",
            "next_required_evidence": [
                "OpenCode approval submitted after the current head commit was created",
                "required GitHub Checks success on the current head",
                "same-head Strix evidence",
                "zero active unresolved review threads",
            ],
        }
    return None


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
        page_size = min(OPEN_PRS_PAGE_SIZE, max_prs - len(prs))
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


def parse_github_datetime(value: str | None) -> datetime | None:
    """Parse a GitHub API timestamp into an aware UTC datetime."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def head_commit_datetime(pr: dict[str, Any]) -> datetime | None:
    """Return the current PR head commit time from the GraphQL commit edge."""
    commits = ((pr.get("commits") or {}).get("nodes") or [])
    if not commits:
        return None
    commit = (commits[-1].get("commit") or {})
    return parse_github_datetime(commit.get("committedDate"))


def review_submitted_datetime(review: dict[str, Any]) -> datetime | None:
    """Return the review submission time as an aware UTC datetime."""
    return parse_github_datetime(review.get("submittedAt"))


def review_matches_current_head(review: dict[str, Any], pr: dict[str, Any]) -> bool:
    """Return whether a review is valid evidence for the current head commit."""
    head = pr.get("headRefOid")
    commit = (review.get("commit") or {}).get("oid")
    if commit != head:
        return False
    head_time = head_commit_datetime(pr)
    if not head_time:
        return True
    submitted_at = review_submitted_datetime(review)
    return bool(submitted_at and submitted_at > head_time)


def stale_current_head_review_reason(pr: dict[str, Any]) -> str | None:
    """Explain why a same-commit OpenCode review is stale for the current head."""
    head = pr.get("headRefOid")
    head_time = head_commit_datetime(pr)
    if not head or not head_time:
        return None
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if not is_opencode_review(review):
            continue
        commit = (review.get("commit") or {}).get("oid")
        if commit != head:
            continue
        submitted_at = review_submitted_datetime(review)
        if not submitted_at:
            return "OpenCode review has no submission timestamp for the current head"
        if submitted_at <= head_time:
            return (
                "OpenCode review does not postdate the current head commit "
                f"({submitted_at.isoformat()} <= {head_time.isoformat()})"
            )
        return None
    return None


def running_check_state(node: dict[str, Any]) -> str:
    """Return running, complete, or absent for a check/status context."""
    status = (node.get("status") or node.get("state") or "").upper()
    if not status:
        return "absent"
    return "running" if status in RUNNING_CHECK_STATES else "complete"


def opencode_progress_state(
    pr: dict[str, Any],
    *,
    stale_after_minutes: int,
    now: datetime | None = None,
) -> str:
    """Return absent, running, stale, or complete for current OpenCode review status."""
    now = now or datetime.now(timezone.utc)
    saw_complete = False
    for node in context_nodes(pr):
        if not is_opencode_context(node):
            continue
        state = running_check_state(node)
        if state == "absent":
            continue
        if state != "running":
            saw_complete = True
            continue
        started_at = parse_github_datetime(node.get("startedAt"))
        if started_at and stale_after_minutes >= 0:
            age_seconds = (now - started_at).total_seconds()
            if age_seconds >= stale_after_minutes * 60:
                return "stale"
        return "running"
    return "complete" if saw_complete else "absent"


def opencode_in_progress(pr: dict[str, Any], *, stale_after_minutes: int | None = None) -> bool:
    """Return whether any OpenCode review status for the PR is still actively running."""
    stale_after = DEFAULT_STALE_OPENCODE_MINUTES if stale_after_minutes is None else stale_after_minutes
    return opencode_progress_state(pr, stale_after_minutes=stale_after) == "running"


def strix_evidence_state(pr: dict[str, Any]) -> str:
    """Return missing, running, or complete for current-head Strix evidence."""
    found = False
    for node in context_nodes(pr):
        if not is_strix_context(node):
            continue
        found = True
        status = (node.get("status") or node.get("state") or "").upper()
        if status in RUNNING_CHECK_STATES:
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
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if not is_opencode_review(review):
            continue
        if not review_matches_current_head(review, pr):
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


def disable_auto_merge(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Disable auto-merge when the current head no longer has fresh review evidence."""
    number = str(pr["number"])
    if dry_run:
        return
    run(["gh", "pr", "merge", number, "--repo", repo, "--disable-auto"])


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


def merge_conflict_guidance(pr: dict[str, Any], merge_state: str) -> str:
    """Return actionable conflict repair guidance for a conflicting PR."""
    base_ref = pr.get("baseRefName") or "base"
    head_ref = pr.get("headRefName") or "head"
    return (
        f"merge conflict: {merge_state}; base={base_ref}, head={head_ref}; "
        f"run `gh pr checkout {pr.get('number', '<pr>')}`, `git fetch origin {base_ref}`, then "
        f"`git merge --no-ff origin/{base_ref}` or `git rebase origin/{base_ref}`; "
        "use `git status --short` to find conflicted files, resolve conflict markers in the PR branch, "
        f"rerun focused checks, and push the same {head_ref} branch "
        "(use `git push --force-with-lease` only if rebased); "
        "do not retry update-branch until the conflict is repaired"
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
    stale_opencode_minutes: int = DEFAULT_STALE_OPENCODE_MINUTES,
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
        return Decision(number, "block", merge_conflict_guidance(pr, merge_state))

    unresolved = unresolved_thread_count(pr)
    if unresolved:
        return Decision(number, "block", f"{unresolved} unresolved review thread(s)")

    if has_current_head_changes_requested(pr):
        return Decision(number, "block", "current-head OpenCode review requested changes")

    current_head_approved = has_current_head_approval(pr)
    stale_review_reason = stale_current_head_review_reason(pr)
    if stale_review_reason and pr.get("autoMergeRequest"):
        disable_auto_merge(repo, pr, dry_run=dry_run)
        return Decision(
            number,
            "disable_auto_merge",
            f"auto-merge disabled; {stale_review_reason}; wait for a fresh same-head OpenCode review",
        )
    if current_head_approved:
        failed_checks = failed_status_checks(pr)
        if failed_checks:
            return Decision(number, "block", f"failed check(s): {', '.join(failed_checks[:5])}")

    if merge_state == "BEHIND" and current_head_approved:
        if not update_branches:
            return Decision(number, "wait", "current-head OpenCode review approved; branch update disabled")
        update_branch(repo, pr, dry_run=dry_run)
        return Decision(
            number,
            "update_branch",
            "current-head OpenCode review approved; branch update requested with workflow GH_TOKEN (github-actions[bot] in GitHub Actions)",
        )

    if current_head_approved:
        if pr.get("autoMergeRequest"):
            return Decision(number, "wait", "current head is approved; auto-merge already enabled")
        if not enable_auto_merge_flag:
            return Decision(number, "wait", "current head is approved; auto-merge disabled by scheduler inputs")
        enable_auto_merge(repo, pr, dry_run=dry_run)
        return Decision(number, "auto_merge", "current head is approved; auto-merge enabled")

    opencode_state = opencode_progress_state(pr, stale_after_minutes=stale_opencode_minutes)
    if opencode_state == "running":
        return Decision(number, "wait", "OpenCode review is already in progress")
    if opencode_state == "stale" and not trigger_reviews:
        return Decision(
            number,
            "wait",
            f"OpenCode review exceeded {stale_opencode_minutes} minute retry threshold; review dispatch disabled",
        )
    if opencode_state == "stale":
        dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
        return Decision(
            number,
            "review_dispatch",
            f"OpenCode review exceeded {stale_opencode_minutes} minute retry threshold; same-head OpenCode re-dispatched",
        )

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
    write_actions_summary(
        decisions,
        counts=counts,
        dry_run=dry_run,
        base_branch=base_branch,
        project_flow=project_flow,
    )
    print(
        json.dumps(
            decision_payload(
                decisions,
                counts=counts,
                dry_run=dry_run,
                base_branch=base_branch,
                project_flow=project_flow,
            ),
            sort_keys=True,
        )
    )


def markdown_cell(value: object) -> str:
    """Escape a value for a compact GitHub Actions summary table cell."""
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def write_actions_summary(
    decisions: list[Decision],
    *,
    counts: dict[str, int],
    dry_run: bool,
    base_branch: str,
    project_flow: str,
) -> None:
    """Append scheduler decisions to the GitHub Actions step summary."""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return

    lines = [
        "## PR review merge scheduler",
        "",
        f"- Base branch: `{base_branch}`",
        f"- Project flow: `{project_flow}`",
        f"- Dry run: `{str(dry_run).lower()}`",
        f"- Inspected PRs: `{len(decisions)}`",
        f"- Actions: `{json.dumps(counts, sort_keys=True)}`",
        "",
        "| PR | Action | Reason |",
        "| ---: | --- | --- |",
    ]
    lines.extend(
        f"| #{decision.pr} | {markdown_cell(decision.action)} | {markdown_cell(decision.reason)} |"
        for decision in decisions
    )
    lines.extend(conflict_repair_summary(decisions))
    lines.extend(update_branch_summary(decisions))
    lines.extend(action_error_summary(decisions))

    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def parse_conflict_reason(reason: str) -> tuple[str, str, str] | None:
    """Extract merge state, base branch, and head branch from conflict guidance."""
    prefix = "merge conflict: "
    if not reason.startswith(prefix):
        return None
    state = reason[len(prefix) :].split(";", 1)[0].strip() or "UNKNOWN"
    base_ref = "base"
    head_ref = "head"
    for segment in reason.split(";"):
        segment = segment.strip()
        if not segment.startswith("base="):
            continue
        branch_bits = segment.split(",")
        for branch_bit in branch_bits:
            key, _, value = branch_bit.strip().partition("=")
            if key == "base" and value:
                base_ref = value
            if key == "head" and value:
                head_ref = value
        break
    return state, base_ref, head_ref


def conflict_repair_summary(decisions: list[Decision]) -> list[str]:
    """Return a GitHub Actions Summary section with concrete conflict repair steps."""
    conflicted = [(decision, parse_conflict_reason(decision.reason)) for decision in decisions]
    conflicted = [(decision, parsed) for decision, parsed in conflicted if parsed is not None]
    if not conflicted:
        return []

    lines = [
        "",
        "### Conflict repair",
        "",
        "GitHub cannot safely update `DIRTY` or `CONFLICTING` PR branches. Repair the PR branch, then push the same branch so OpenCode and required checks can run on the new head.",
        "`update-branch` is not a conflict resolver: the scheduler waits here because GitHub cannot choose which side of a conflicted hunk is correct.",
    ]
    for decision, parsed in conflicted:
        assert parsed is not None
        state, base_ref, head_ref = parsed
        base_remote = f"origin/{base_ref}"
        lines.extend(
            [
                "",
                f"PR #{decision.pr} is `{state}` against `{base_ref}` from `{head_ref}`:",
                "",
                "```bash",
                f"gh pr checkout {decision.pr}",
                f"git fetch origin {shlex.quote(base_ref)}",
                "# choose merge or rebase",
                f"git merge --no-ff {shlex.quote(base_remote)}",
                f"# git rebase {shlex.quote(base_remote)}",
                "git status --short",
                "# resolve conflict markers in the PR branch",
                "git add <resolved-files>",
                "# run the focused checks for the changed area",
                "git push",
                "# if you chose rebase: git push --force-with-lease",
                "```",
            ]
        )
    return lines


def update_branch_summary(decisions: list[Decision]) -> list[str]:
    """Return a GitHub Actions Summary section explaining branch update mutations."""
    updates = [decision for decision in decisions if decision.action == "update_branch"]
    if not updates:
        return []
    pr_list = ", ".join(f"#{decision.pr}" for decision in updates)
    return [
        "",
        "### Branch update requests",
        "",
        f"Requested `update-branch` for PR {pr_list} with the workflow `GITHUB_TOKEN`, guarded by the observed `expected_head_sha`.",
        "This is intentionally done inside GitHub Actions, not from a maintainer's local `gh` credential, so the mechanical update is attributable to the automation actor.",
        "This branch-update API path needs `pull-requests: write`; it does not require the scheduler job to widen repository `contents` to write.",
        "When repository permissions allow the mutation, GitHub records the resulting branch update as `github-actions[bot]`.",
        "The updated head is not merge evidence by itself. Wait for the new head to receive OpenCode approval, Strix evidence, required checks, and unresolved-thread checks before merge or auto-merge.",
    ]


def action_error_summary(decisions: list[Decision]) -> list[str]:
    """Return a GitHub Actions Summary section for mutation failures."""
    errors = [decision for decision in decisions if decision.action == "action_error"]
    if not errors:
        return []
    lines = [
        "",
        "### Action errors",
        "",
        "These are scheduler or GitHub permission/runtime failures, not source-code review findings.",
    ]
    for decision in errors:
        lines.append(f"- PR #{decision.pr}: {decision.reason}")
    return lines


def bounded_error_summary(text: str, *, limit: int = 500) -> str:
    """Cap an action-error message without dropping the actionable prefix."""
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def summarize_action_error(exc: RuntimeError) -> str:
    """Return a compact, log-safe scheduler action error summary."""
    lines = [line.strip() for line in str(exc).splitlines() if line.strip()]
    if not lines:
        return "scheduler action failed without stderr"
    summary = "; ".join(lines[:2])
    lower_summary = summary.lower()
    if "resource not accessible by integration" in lower_summary:
        if "mergepullrequest" in lower_summary or "enablepullrequestautomerge" in lower_summary or "gh pr merge" in lower_summary:
            summary = (
                f"{summary}; scheduler GitHub token could not perform merge or auto-merge. "
                "Merging through GitHub Actions needs an explicit repo policy exception for scheduler-job `contents: write`; otherwise leave auto-merge disabled and keep update-branch on the lower-privilege PR-write path."
            )
        elif "update-branch" in lower_summary:
            summary = (
                f"{summary}; scheduler GitHub token could not update the PR branch. "
                "Give the scheduler job `pull-requests: write`, then rerun with the same expected-head guard; do not widen `contents` just for update-branch."
            )
        else:
            summary = (
                f"{summary}; scheduler GitHub token lacks a required repository mutation permission. "
                "Fix the scheduler job permissions instead of posting a code-review finding."
            )
    if "expected_head_sha" in lower_summary and ("422" in lower_summary or "head" in lower_summary):
        summary = (
            f"{summary}; the PR head likely changed after inspection. Rerun the scheduler so it reads the new head before mutating."
        )
    return bounded_error_summary(summary)


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
    assert decision.reason == "failed check(s): strix"
    sample["statusCheckRollup"]["contexts"]["nodes"] = []
    sample["mergeStateStatus"] = "DIRTY"
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
    assert "gh pr checkout 1" in decision.reason
    assert "git fetch origin main" in decision.reason
    assert "git merge --no-ff origin/main" in decision.reason
    assert "git rebase origin/main" in decision.reason
    assert "git status --short" in decision.reason
    assert "resolve conflict markers" in decision.reason
    conflict_guidance = decision_guidance(decision)
    assert conflict_guidance
    assert conflict_guidance["type"] == "merge_conflict_repair"
    assert conflict_guidance["merge_state"] == "DIRTY"
    assert "update-branch cannot choose" in conflict_guidance["automation_limit"]
    assert "git status --short" in conflict_guidance["commands"]
    assert contract_decision(Decision(1, "update_branch", "ok")) == "UPDATE_BRANCH"
    assert contract_decision(Decision(1, "wait", "ok")) == "WAIT"
    assert contract_decision(Decision(1, "action_error", "ok")) == "WAIT"
    assert contract_decision(Decision(1, "auto_merge", "ok")) == "NO_ACTION"
    assert contract_decision(Decision(1, "skip", "ok")) == "NO_ACTION"
    assert (
        contract_decision(Decision(1, "block", "current-head OpenCode review requested changes"))
        == "REQUEST_CHANGES"
    )
    assert contract_decision(Decision(1, "block", "merge conflict: DIRTY")) == "WAIT"
    update_guidance = decision_guidance(Decision(1, "update_branch", "ok"))
    assert update_guidance
    assert update_guidance["actor"] == "github-actions[bot]"
    assert update_guidance["head_guard"] == "expected_head_sha"
    assert decision_guidance(Decision(1, "wait", "ok")) is None
    payload = decision_payload(
        [Decision(1, "update_branch", "ok")],
        counts={"update_branch": 1},
        dry_run=True,
        base_branch="main",
        project_flow="github-flow",
    )
    assert payload["schema_version"] == "pr-review-merge-scheduler/v1"
    assert payload["decisions"][0]["contract_decision"] == "UPDATE_BRANCH"
    assert payload["decisions"][0]["guidance"]["actor"] == "github-actions[bot]"
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
    parser.add_argument(
        "--stale-opencode-minutes",
        type=int,
        default=int(os.environ.get("STALE_OPENCODE_MINUTES", str(DEFAULT_STALE_OPENCODE_MINUTES))),
    )
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
                stale_opencode_minutes=args.stale_opencode_minutes,
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
