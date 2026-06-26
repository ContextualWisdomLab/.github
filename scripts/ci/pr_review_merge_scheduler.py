#!/usr/bin/env python3
"""Inspect PR review state and drive centralized OpenCode merge automation."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


PULL_REQUEST_FIELDS_FRAGMENT = """\
fragment SchedulerPullRequestFields on PullRequest {
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
  isCrossRepository
  maintainerCanModify
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
    nodes { id isResolved isOutdated }
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
"""

OPEN_PRS_QUERY = """\
query($owner: String!, $name: String!, $pageSize: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequests(first: $pageSize, after: $cursor, states: OPEN, orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        ...SchedulerPullRequestFields
      }
    }
  }
}
""" + PULL_REQUEST_FIELDS_FRAGMENT

PR_BY_NUMBER_QUERY = """\
query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      ...SchedulerPullRequestFields
    }
  }
}
""" + PULL_REQUEST_FIELDS_FRAGMENT

OPEN_PRS_PAGE_SIZE = 25
DEFAULT_STALE_OPENCODE_MINUTES = 45
RUNNING_CHECK_STATES = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}
FAILED_CHECK_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE"}
ACTION_REQUIRED_CONCLUSIONS = {"ACTION_REQUIRED"}
REVIEW_BODY_HEAD_SHA_RE = re.compile(r"Head SHA:\s*`([0-9a-fA-F]{40})`")
REST_MERGEABLE_STATE_MAP = {
    "behind": "BEHIND",
    "blocked": "BLOCKED",
    "clean": "CLEAN",
    "dirty": "DIRTY",
    "draft": "DRAFT",
    "has_hooks": "HAS_HOOKS",
    "unknown": "UNKNOWN",
    "unstable": "UNSTABLE",
}
REST_MERGEABLE_STATES = set(REST_MERGEABLE_STATE_MAP.values())


@dataclass
class Decision:
    """Scheduler decision for a single pull request."""

    pr: int
    action: str
    reason: str
    notes: tuple[str, ...] = ()


RESOLVE_REVIEW_THREAD_MUTATION = """\
mutation($threadId: ID!) {
  resolveReviewThread(input: {threadId: $threadId}) {
    thread { id isResolved }
  }
}
"""


def scrub_sensitive_data(text: str | None) -> str | None:
    """Mask sensitive tokens in text to prevent secret leakage."""
    if not text:
        return text
    text = re.sub(r'(?i)(bearer\s+)[^\s"\'\\]+', r'\1***', text)
    text = re.sub(r'(?i)(token\s+)[^\s"\'\\]+', r'\1***', text)
    text = re.sub(r'(gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)', '***', text)
    return text


def contract_decision(decision: Decision) -> str:
    """Map scheduler actions into the bounded PR decision contract."""
    if decision.action == "update_branch":
        return "UPDATE_BRANCH"
    if decision.action in {"wait", "security_dispatch", "review_dispatch", "disable_auto_merge", "action_error"}:
        return "WAIT"
    if decision.action in {"skip", "auto_merge", "merge"}:
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
        "schema_version": "pr-review-merge-scheduler/v2",
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
    if decision.notes:
        entry["notes"] = list(decision.notes)
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
    action_required = parse_workflow_action_required_reason(decision.reason)
    if action_required:
        return {
            "type": "workflow_action_required",
            "checks": action_required,
            "summary": "A GitHub Actions run is waiting for workflow approval or a repository policy unblock; this is not a source-code failure by itself.",
            "automation_limit": "The scheduler cannot safely reinterpret an ACTION_REQUIRED run as passed or failed, and should not publish a code-review finding from it.",
            "next_required_evidence": [
                "GitHub Actions run approval or repository policy unblock",
                "current-head check rerun after the unblock",
                "OpenCode approval on the exact current head",
                "same-head Strix evidence",
                "zero active unresolved review threads",
            ],
        }
    external_update = parse_external_head_update_reason(decision.reason)
    if external_update:
        return {
            "type": "external_head_update_required",
            "head_repository": external_update,
            "summary": "The PR can be reviewed centrally, but this head branch is not writable by the scheduler credential.",
            "automation_limit": "The scheduler should not skip the PR; it waits for the author to update the branch or for maintainers to enable a writable head path.",
            "next_required_evidence": [
                "PR author updates the head branch against the base branch, or maintainer edit permission is enabled",
                "new head SHA after the branch update",
                "OpenCode approval on that exact new head",
                "same-head Strix evidence",
                "required GitHub Checks success",
                "zero active unresolved review threads",
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
    if decision.action == "merge":
        return {
            "type": "github_actions_direct_merge",
            "actor": "github-actions[bot]",
            "token": "workflow GITHUB_TOKEN",
            "required_permission": "contents: write",
            "head_guard": "gh pr merge --match-head-commit",
            "summary": "GitHub Actions performed an immediate guarded merge because repo policy does not use native auto-merge for this queue.",
            "next_required_evidence": [
                "merge commit recorded by GitHub",
                "merged head SHA matches the inspected current head",
                "no active unresolved review threads before merge",
                "same-head OpenCode approval before merge",
                "required GitHub Checks success before merge",
            ],
        }
    if decision.action == "disable_auto_merge":
        return {
            "type": "unsafe_auto_merge_disabled",
            "summary": "Auto-merge was disabled because the current PR state is not safe to merge automatically.",
            "next_required_evidence": [
                "the unsafe condition described in reason is repaired",
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
    try:
        process = subprocess.run(
            argv,
            input=stdin,
            capture_output=True,
            text=True,
            shell=False,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        scrubbed_args = scrub_sensitive_data(' '.join(argv))
        scrubbed_stderr = scrub_sensitive_data(exc.stderr or "")
        raise RuntimeError(
            f"Command failed ({exc.returncode}): {scrubbed_args}\n{scrubbed_stderr}"
        ) from exc
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

    enrich_rest_mergeable_states(repo, prs)
    return prs


def fetch_pr(repo: str, number: int) -> list[dict[str, Any]]:
    """Fetch one pull request by number using the same evidence shape as the queue scan."""
    owner, name = split_repo(repo)
    payload = gh_graphql(PR_BY_NUMBER_QUERY, owner=owner, name=name, number=number)
    pr = payload["data"]["repository"].get("pullRequest")
    prs = [pr] if pr else []
    enrich_rest_mergeable_states(repo, prs)
    return prs


def fetch_rest_mergeable_state(repo: str, number: int) -> str:
    """Fetch and normalize GitHub REST mergeable_state for one pull request."""
    raw_state = run(
        [
            "gh",
            "api",
            f"repos/{repo}/pulls/{number}",
            "--jq",
            ".mergeable_state // \"\"",
        ]
    ).strip()
    return REST_MERGEABLE_STATE_MAP.get(raw_state.lower(), raw_state.upper())


def enrich_rest_mergeable_states(repo: str, prs: list[dict[str, Any]]) -> None:
    """Attach REST mergeability evidence to GraphQL pull request payloads."""
    for pr in prs:
        try:
            pr["restMergeableState"] = fetch_rest_mergeable_state(repo, int(pr["number"]))
        except RuntimeError as exc:
            pr["restMergeableStateError"] = bounded_error_summary(str(exc))


def effective_merge_state(pr: dict[str, Any]) -> str:
    """Return the safest merge state from GraphQL plus REST mergeability evidence."""
    graph_state = (pr.get("mergeStateStatus") or "").upper()
    rest_state = (pr.get("restMergeableState") or "").upper()
    if rest_state in REST_MERGEABLE_STATES:
        return rest_state
    if graph_state in {"BEHIND", "DIRTY", "CONFLICTING", "UNKNOWN"}:
        return graph_state
    return rest_state or graph_state


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


def review_matches_current_head(review: dict[str, Any], pr: dict[str, Any]) -> bool:
    """Return whether a review is valid evidence for the current head commit."""
    head = pr.get("headRefOid")
    commit = (review.get("commit") or {}).get("oid")
    if not head or commit != head:
        return False
    body_head = review_body_head_sha(review)
    return body_head is None or body_head.lower() == head.lower()


def review_body_head_sha(review: dict[str, Any]) -> str | None:
    """Return the last explicit Head SHA from an OpenCode review body."""
    body = review.get("body") or ""
    matches = REVIEW_BODY_HEAD_SHA_RE.findall(body)
    return matches[-1] if matches else None


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


def outdated_thread_ids(pr: dict[str, Any]) -> list[str]:
    """Return unresolved review-thread IDs GitHub already marks outdated."""
    threads = ((pr.get("reviewThreads") or {}).get("nodes") or [])
    return [
        thread["id"]
        for thread in threads
        if thread.get("id") and not thread.get("isResolved") and thread.get("isOutdated")
    ]


def resolve_review_thread(thread_id: str) -> None:
    """Resolve one GitHub review thread by GraphQL node ID."""
    gh_graphql(RESOLVE_REVIEW_THREAD_MUTATION, threadId=thread_id)


def resolve_outdated_review_threads(pr: dict[str, Any], *, dry_run: bool) -> int:
    """Resolve obsolete diff conversations before active-thread merge checks."""
    thread_ids = outdated_thread_ids(pr)
    if not thread_ids:
        return 0
    if dry_run:
        return len(thread_ids)
    require_github_actions_mutation_actor("resolve-outdated-review-thread")
    for thread_id in thread_ids:
        resolve_review_thread(thread_id)
    return len(thread_ids)


def with_outdated_thread_cleanup_note(decision: Decision, count: int, *, dry_run: bool) -> Decision:
    """Annotate a decision with the outdated-thread cleanup side effect."""
    if count <= 0:
        return decision
    verb = "Would resolve" if dry_run else "Resolved"
    note = (
        f"{verb} {count} outdated review thread(s) before active unresolved-thread checks; "
        "outdated diff comments are not current-head review blockers."
    )
    return Decision(decision.pr, decision.action, decision.reason, (*decision.notes, note))


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
            if conclusion in FAILED_CHECK_CONCLUSIONS:
                if is_strix_context(node) and "strix" in successful_status_contexts:
                    continue
                failed.append(node.get("name") or "check-run")
        else:
            state = (node.get("state") or "").upper()
            if state in {"FAILURE", "ERROR"}:
                failed.append(node.get("context") or "status-context")
    return failed


def action_required_checks(pr: dict[str, Any]) -> list[str]:
    """Return check-run names that need explicit GitHub Actions approval or unblocking."""
    required: list[str] = []
    for node in context_nodes(pr):
        if node.get("__typename") != "CheckRun":
            continue
        conclusion = (node.get("conclusion") or "").upper()
        if conclusion in ACTION_REQUIRED_CONCLUSIONS:
            required.append(node.get("name") or "check-run")
    return required


def workflow_action_required_reason(checks: list[str]) -> str:
    """Return a scheduler reason for ACTION_REQUIRED check runs."""
    visible = checks[:5]
    suffix = f", +{len(checks) - len(visible)} more" if len(checks) > len(visible) else ""
    return (
        f"workflow action required: {', '.join(visible)}{suffix}; "
        "approve or unblock the GitHub Actions run before treating checks as failed or passed"
    )


def enable_auto_merge(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Enable merge-commit auto-merge for a PR at its current head."""
    number = str(pr["number"])
    head = pr["headRefOid"]
    if dry_run:
        return
    require_github_actions_mutation_actor("enable-auto-merge")
    run(["gh", "pr", "merge", number, "--repo", repo, "--auto", "--merge", "--match-head-commit", head])


def merge_pr(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Merge a current-head-approved PR immediately with a head guard."""
    number = str(pr["number"])
    head = pr["headRefOid"]
    if dry_run:
        return
    require_github_actions_mutation_actor("direct-merge")
    run(["gh", "pr", "merge", number, "--repo", repo, "--merge", "--match-head-commit", head])


def disable_auto_merge(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Disable auto-merge when the current head no longer has fresh review evidence."""
    number = str(pr["number"])
    if dry_run:
        return
    require_github_actions_mutation_actor("disable-auto-merge")
    run(["gh", "pr", "merge", number, "--repo", repo, "--disable-auto"])


def disable_auto_merge_decision(
    repo: str,
    pr: dict[str, Any],
    *,
    dry_run: bool,
    reason: str,
) -> Decision:
    """Disable auto-merge and return a WAIT decision with the concrete unsafe reason."""
    disable_auto_merge(repo, pr, dry_run=dry_run)
    return Decision(pr["number"], "disable_auto_merge", f"auto-merge disabled; {reason}")


def update_branch(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Ask GitHub to update a PR branch, guarded by the observed head SHA."""
    number = str(pr["number"])
    head = pr["headRefOid"]
    if dry_run:
        return
    require_github_actions_mutation_actor("update-branch")
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


def can_update_pr_head(repo: str, pr: dict[str, Any]) -> bool:
    """Return whether the scheduler may try to mutate the PR head branch."""
    head_repo = (pr.get("headRepository") or {}).get("nameWithOwner")
    if head_repo == repo:
        return True
    return bool(pr.get("maintainerCanModify"))


def non_mutable_head_reason(repo: str, pr: dict[str, Any]) -> str:
    """Explain why a PR can be reviewed but not mechanically updated."""
    head_repo = (pr.get("headRepository") or {}).get("nameWithOwner") or "<unknown>"
    if head_repo == repo:
        return "current-head OpenCode review approved, but same-repository head update permission is unavailable"
    return (
        f"current-head OpenCode review approved, but head repo {head_repo} is external and not writable by "
        "the scheduler credential; ask the PR author to update the branch against the base branch, or enable "
        "a maintainer-writable head path before rerunning"
    )


def require_github_actions_mutation_actor(action: str) -> None:
    """Refuse mutating PR branches from a maintainer-local gh credential."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError(
            f"{action} refused outside GitHub Actions; dispatch PR Review Merge Scheduler "
            "so the workflow GITHUB_TOKEN performs the mutation as github-actions[bot]"
        )
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError(
            f"{action} refused without GH_TOKEN; configure the scheduler job to pass "
            "secrets.GITHUB_TOKEN through GH_TOKEN so the mutation is attributable to github-actions[bot]"
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
    merge_mode: str = "auto",
    stale_opencode_minutes: int = DEFAULT_STALE_OPENCODE_MINUTES,
) -> Decision:
    """Decide and optionally act on one pull request's merge-readiness state."""
    number = pr["number"]
    base_ref = pr.get("baseRefName")

    if pr.get("isDraft"):
        return Decision(number, "skip", "draft PR")
    if base_ref != base_branch:
        return Decision(number, "skip", f"base branch is {base_ref}; expected {base_branch}")

    outdated_cleanup_count = resolve_outdated_review_threads(pr, dry_run=dry_run)

    def finish(decision: Decision) -> Decision:
        """Attach outdated-thread cleanup evidence to the final decision."""
        return with_outdated_thread_cleanup_note(
            decision,
            outdated_cleanup_count,
            dry_run=dry_run,
        )

    def decide(action: str, reason: str) -> Decision:
        """Create a decision after applying shared cleanup notes."""
        return finish(Decision(number, action, reason))

    merge_state = effective_merge_state(pr)
    if merge_state == "UNKNOWN":
        if pr.get("autoMergeRequest"):
            return finish(
                disable_auto_merge_decision(
                    repo,
                    pr,
                    dry_run=dry_run,
                    reason="mergeability is still being calculated; wait for GitHub mergeability evidence before re-enabling auto-merge",
                )
            )
        return decide("wait", "mergeability is still being calculated")

    if merge_state in {"DIRTY", "CONFLICTING"}:
        if pr.get("autoMergeRequest"):
            return finish(
                disable_auto_merge_decision(
                    repo,
                    pr,
                    dry_run=dry_run,
                    reason=f"{merge_conflict_guidance(pr, merge_state)}; repair the conflict before re-enabling auto-merge",
                )
            )
        return decide("block", merge_conflict_guidance(pr, merge_state))

    unresolved = unresolved_thread_count(pr)
    if unresolved:
        if pr.get("autoMergeRequest"):
            return finish(
                disable_auto_merge_decision(
                    repo,
                    pr,
                    dry_run=dry_run,
                    reason=f"{unresolved} unresolved review thread(s); resolve the active thread(s) before re-enabling auto-merge",
                )
            )
        return decide("block", f"{unresolved} unresolved review thread(s)")

    if has_current_head_changes_requested(pr):
        if pr.get("autoMergeRequest"):
            return finish(
                disable_auto_merge_decision(
                    repo,
                    pr,
                    dry_run=dry_run,
                    reason="current-head OpenCode review requested changes; address the review before re-enabling auto-merge",
                )
            )
        return decide("block", "current-head OpenCode review requested changes")

    current_head_approved = has_current_head_approval(pr)
    if current_head_approved:
        failed_checks = failed_status_checks(pr)
        if failed_checks:
            if pr.get("autoMergeRequest"):
                return finish(
                    disable_auto_merge_decision(
                        repo,
                        pr,
                        dry_run=dry_run,
                        reason=f"failed check(s): {', '.join(failed_checks[:5])}; fix or rerun checks before re-enabling auto-merge",
                    )
                )
            return decide("block", f"failed check(s): {', '.join(failed_checks[:5])}")

    workflow_action_required = action_required_checks(pr)
    if workflow_action_required:
        reason = workflow_action_required_reason(workflow_action_required)
        if pr.get("autoMergeRequest"):
            return finish(
                disable_auto_merge_decision(
                    repo,
                    pr,
                    dry_run=dry_run,
                    reason=f"{reason}; wait for current-head checks to rerun before re-enabling auto-merge",
                )
            )
        return decide("wait", reason)

    if merge_state == "BEHIND" and current_head_approved:
        if not update_branches:
            return decide("wait", "current-head OpenCode review approved; branch update disabled")
        if not can_update_pr_head(repo, pr):
            return decide("wait", non_mutable_head_reason(repo, pr))
        had_auto_merge = bool(pr.get("autoMergeRequest"))
        if had_auto_merge:
            disable_auto_merge(repo, pr, dry_run=dry_run)
        update_branch(repo, pr, dry_run=dry_run)
        prefix = "auto-merge disabled before branch update; " if had_auto_merge else ""
        return decide(
            "update_branch",
            f"{prefix}current-head OpenCode review approved; branch update requested with workflow GH_TOKEN (github-actions[bot] in GitHub Actions)",
        )

    if current_head_approved:
        if pr.get("autoMergeRequest"):
            return decide("wait", "current head is approved; auto-merge already enabled")
        if not enable_auto_merge_flag:
            return decide("wait", "current head is approved; auto-merge disabled by scheduler inputs")
        if merge_mode == "disabled":
            return decide("wait", "current head is approved; merge mode disabled by scheduler inputs")
        if merge_mode == "direct":
            if merge_state != "CLEAN":
                return decide(
                    "wait",
                    f"current head is approved; direct merge waits for CLEAN mergeability, current merge state is {merge_state}",
                )
            merge_pr(repo, pr, dry_run=dry_run)
            return decide(
                "merge",
                "current head is approved; direct merge requested with workflow GH_TOKEN and --match-head-commit",
            )
        if merge_mode != "auto":
            return decide("wait", f"current head is approved; unsupported merge mode: {merge_mode}")
        enable_auto_merge(repo, pr, dry_run=dry_run)
        return decide("auto_merge", "current head is approved; auto-merge enabled")

    opencode_state = opencode_progress_state(pr, stale_after_minutes=stale_opencode_minutes)
    if opencode_state == "running":
        return decide("wait", "OpenCode review is already in progress")
    if opencode_state == "stale" and not trigger_reviews:
        return decide(
            "wait",
            f"OpenCode review exceeded {stale_opencode_minutes} minute retry threshold; review dispatch disabled",
        )
    if opencode_state == "stale":
        dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
        return decide(
            "review_dispatch",
            f"OpenCode review exceeded {stale_opencode_minutes} minute retry threshold; same-head OpenCode re-dispatched",
        )

    if trigger_reviews:
        strix_state = strix_evidence_state(pr)
        if strix_state == "missing":
            dispatch_strix_evidence(repo, security_workflow, pr, dry_run=dry_run)
            return decide(
                "security_dispatch",
                "current head has no completed Strix evidence; same-head Strix dispatched",
            )
        if strix_state == "running":
            return decide("wait", "same-head Strix evidence is still running")
        # Legacy trusted-base Strix self-test sentinel while this scheduler rollout lands:
        # same-head Strix and OpenCode dispatched
        dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
        return decide(
            "review_dispatch",
            "current head has completed Strix evidence; same-head OpenCode dispatched",
        )

    if pr.get("autoMergeRequest"):
        return finish(
            disable_auto_merge_decision(
                repo,
                pr,
                dry_run=dry_run,
                reason="current head has no OpenCode approval; wait for fresh same-head approval before re-enabling auto-merge",
            )
        )

    return decide("block", "current head has no OpenCode approval")


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
    lines.extend(outdated_thread_cleanup_summary(decisions))
    lines.extend(update_branch_summary(decisions))
    lines.extend(external_head_update_summary(decisions))
    lines.extend(workflow_action_required_summary(decisions))
    lines.extend(action_error_summary(decisions))

    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        handle.write("\n")


def parse_conflict_reason(reason: str) -> tuple[str, str, str] | None:
    """Extract merge state, base branch, and head branch from conflict guidance."""
    prefix = "merge conflict: "
    conflict_start = reason.find(prefix)
    if conflict_start < 0:
        return None
    conflict_reason = reason[conflict_start:]
    state = conflict_reason[len(prefix) :].split(";", 1)[0].strip() or "UNKNOWN"
    base_ref = "base"
    head_ref = "head"
    for segment in conflict_reason.split(";"):
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
        "When GitHub shows `Conflicting`, or the API reports `DIRTY`/`CONFLICTING`, this is not a code-review finding and it is not an `update-branch` candidate. Repair the PR branch, then push the same branch so OpenCode and required checks can run on the new head.",
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


def outdated_thread_cleanup_summary(decisions: list[Decision]) -> list[str]:
    """Return a summary section for obsolete diff conversations resolved by the scheduler."""
    cleanup_notes = [
        (decision, note)
        for decision in decisions
        for note in decision.notes
        if "outdated review thread" in note
    ]
    if not cleanup_notes:
        return []

    lines = [
        "",
        "### Outdated review threads",
        "",
        "GitHub `Outdated` review threads belong to obsolete diff hunks. The scheduler resolves them before counting active unresolved review threads, so stale UI conversations do not block current-head decisions.",
    ]
    lines.extend(f"- PR #{decision.pr}: {note}" for decision, note in cleanup_notes)
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
        "The scheduler refuses a non-dry-run `update-branch` outside GitHub Actions; dispatch the workflow instead of running the mutation locally.",
        "This branch-update API path needs `pull-requests: write`; it does not require the scheduler job to widen repository `contents` to write.",
        "When repository permissions allow the mutation, GitHub records the resulting branch update as `github-actions[bot]`.",
        "The updated head is not merge evidence by itself. Wait for the new head to receive OpenCode approval, Strix evidence, required checks, and unresolved-thread checks before merge or auto-merge.",
    ]


def parse_external_head_update_reason(reason: str) -> str | None:
    """Extract the external head repository from non-mutable update guidance."""
    match = re.search(r"head repo ([^\s]+) is external and not writable", reason)
    if not match:
        return None
    return match.group(1)


def external_head_update_summary(decisions: list[Decision]) -> list[str]:
    """Return a GitHub Actions Summary section for non-mutable external PR heads."""
    external_waits = [
        (decision, parse_external_head_update_reason(decision.reason))
        for decision in decisions
        if parse_external_head_update_reason(decision.reason)
    ]
    if not external_waits:
        return []

    lines = [
        "",
        "### External head update required",
        "",
        "These PRs remain in the central review pipeline, but their head branches are not writable by the scheduler credential. This is a mutation-capability limit, not a fork/non-fork onboarding exception.",
    ]
    for decision, head_repo in external_waits:
        lines.extend(
            [
                "",
                f"- PR #{decision.pr}: ask the author of `{head_repo}` to update the branch against the base branch, or enable maintainer edit permission and rerun the scheduler.",
            ]
        )
    return lines


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


def parse_workflow_action_required_reason(reason: str) -> str | None:
    """Extract ACTION_REQUIRED check names from a scheduler reason."""
    marker = "workflow action required:"
    marker_start = reason.find(marker)
    if marker_start < 0:
        return None
    tail = reason[marker_start + len(marker) :].strip()
    checks = tail.split(";", 1)[0].strip()
    return checks or None


def workflow_action_required_summary(decisions: list[Decision]) -> list[str]:
    """Return a GitHub Actions Summary section for ACTION_REQUIRED waits."""
    waits = [
        decision
        for decision in decisions
        if parse_workflow_action_required_reason(decision.reason)
    ]
    if not waits:
        return []
    lines = [
        "",
        "### Workflow action required",
        "",
        "`ACTION_REQUIRED` means GitHub Actions is waiting for approval or a repository policy unblock. It is not a source-code failure and should not be converted into an OpenCode finding.",
        "Unblock or approve the run, then rerun the scheduler so it can read the new current-head check state.",
    ]
    for decision in waits:
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
        "restMergeableState": "CLEAN",
        "isDraft": False,
        "isCrossRepository": False,
        "maintainerCanModify": False,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "reviewDecision": "REVIEW_REQUIRED",
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "oid": "abc",
                        "committedDate": "2026-06-25T16:38:22Z",
                    }
                }
            ]
        },
        "reviewThreads": {"nodes": []},
        "reviews": {
            "nodes": [
                {
                    "state": "APPROVED",
                    "author": {"login": "opencode-agent"},
                    "body": "OpenCode Agent approved this head.",
                    "submittedAt": "2026-06-25T15:42:19Z",
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
    sample["restMergeableState"] = "BEHIND"
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
    sample["restMergeableState"] = "DIRTY"
    sample["autoMergeRequest"] = {"enabledAt": "2026-01-01T00:02:00Z"}
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
    assert decision.action == "disable_auto_merge"
    assert "merge conflict: DIRTY" in decision.reason
    sample["restMergeableState"] = "UNKNOWN"
    sample["autoMergeRequest"] = None
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
    assert decision.action == "wait"
    assert "mergeability is still being calculated" in decision.reason
    sample["restMergeableState"] = "CLEAN"
    sample["autoMergeRequest"] = {"enabledAt": "2026-01-01T00:02:00Z"}
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
    assert decision.action == "disable_auto_merge"
    assert "failed check(s): strix" in decision.reason
    sample["autoMergeRequest"] = None
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
    sample["reviews"]["nodes"] = [
        {
            "state": "CHANGES_REQUESTED",
            "author": {"login": "opencode-agent"},
            "commit": {"oid": "abc"},
        }
    ]
    sample["autoMergeRequest"] = {"enabledAt": "2026-01-01T00:02:00Z"}
    assert has_current_head_changes_requested(sample)
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
    assert decision.action == "disable_auto_merge"
    assert "current-head OpenCode review requested changes" in decision.reason
    sample["autoMergeRequest"] = None
    sample["statusCheckRollup"]["contexts"]["nodes"].append(
        {"__typename": "CheckRun", "name": "opencode-review", "status": "IN_PROGRESS"}
    )
    assert opencode_in_progress(sample)
    sample["statusCheckRollup"]["contexts"]["nodes"] = []
    sample["mergeStateStatus"] = "BEHIND"
    sample["restMergeableState"] = ""
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
    sample["headRepository"] = {"nameWithOwner": "external/repo"}
    sample["isCrossRepository"] = True
    sample["maintainerCanModify"] = False
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
    assert decision.action == "wait"
    assert "external/repo" in decision.reason
    assert decision_guidance(decision)["type"] == "external_head_update_required"
    sample["maintainerCanModify"] = True
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
    sample["headRepository"] = {"nameWithOwner": "owner/repo"}
    sample["isCrossRepository"] = False
    sample["maintainerCanModify"] = False
    sample["autoMergeRequest"] = {"enabledAt": "2026-01-01T00:02:00Z"}
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
    assert "auto-merge disabled before branch update" in decision.reason
    sample["autoMergeRequest"] = None
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
    sample["autoMergeRequest"] = {"enabledAt": "2026-01-01T00:02:00Z"}
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
    assert decision.action == "disable_auto_merge"
    assert "merge conflict: DIRTY" in decision.reason
    conflict_guidance = decision_guidance(decision)
    assert conflict_guidance
    assert conflict_guidance["type"] == "merge_conflict_repair"
    sample["autoMergeRequest"] = None
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
    assert contract_decision(Decision(1, "disable_auto_merge", "ok")) == "WAIT"
    assert contract_decision(Decision(1, "auto_merge", "ok")) == "NO_ACTION"
    assert contract_decision(Decision(1, "merge", "ok")) == "NO_ACTION"
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
    disable_guidance = decision_guidance(Decision(1, "disable_auto_merge", "ok"))
    assert disable_guidance
    assert disable_guidance["type"] == "unsafe_auto_merge_disabled"
    merge_guidance = decision_guidance(Decision(1, "merge", "ok"))
    assert merge_guidance
    assert merge_guidance["type"] == "github_actions_direct_merge"
    assert merge_guidance["head_guard"] == "gh pr merge --match-head-commit"
    assert decision_guidance(Decision(1, "wait", "ok")) is None
    payload = decision_payload(
        [Decision(1, "update_branch", "ok")],
        counts={"update_branch": 1},
        dry_run=True,
        base_branch="main",
        project_flow="github-flow",
    )
    assert payload["schema_version"] == "pr-review-merge-scheduler/v2"
    assert payload["decisions"][0]["contract_decision"] == "UPDATE_BRANCH"
    assert payload["decisions"][0]["guidance"]["actor"] == "github-actions[bot]"
    payload = decision_payload(
        [Decision(1, "merge", "ok")],
        counts={"merge": 1},
        dry_run=True,
        base_branch="main",
        project_flow="github-flow",
    )
    assert payload["decisions"][0]["contract_decision"] == "NO_ACTION"
    assert payload["decisions"][0]["guidance"]["type"] == "github_actions_direct_merge"
    print("self-test passed")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse scheduler CLI arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--base-branch", default=os.environ.get("DEFAULT_BRANCH", ""))
    parser.add_argument("--project-flow", default=os.environ.get("PROJECT_FLOW", ""))
    parser.add_argument("--max-prs", type=int, default=100)
    parser.add_argument("--pr-number", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--trigger-reviews", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--enable-auto-merge", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--merge-mode",
        choices=("auto", "direct", "disabled"),
        default=os.environ.get("MERGE_MODE", "auto"),
    )
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
    if args.pr_number < 0:
        raise SystemExit("--pr-number must not be negative")
    prs = fetch_pr(args.repo, args.pr_number) if args.pr_number else fetch_open_prs(args.repo, args.max_prs)
    decisions = []
    for pr in prs:
        try:
            decision = inspect_pr(
                args.repo,
                pr,
                dry_run=args.dry_run,
                trigger_reviews=args.trigger_reviews,
                enable_auto_merge_flag=args.enable_auto_merge,
                merge_mode=args.merge_mode,
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
