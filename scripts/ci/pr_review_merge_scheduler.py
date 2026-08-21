#!/usr/bin/env python3
"""Inspect PR review state and drive centralized OpenCode merge automation."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote


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
        messageHeadline
      }
    }
  }
  reviewThreads(first: 100) {
    nodes { id isResolved isOutdated }
  }
  files(first: 20) {
    nodes { path }
  }
  reviews(last: 100) {
    nodes {
      databaseId
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
          detailsUrl
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
# Must exceed the 45-minute OpenCode job cap plus typical runner-queue wait.
# QUEUED counts as running and the age clock starts at check creation, so this
# remains deliberately larger than the job cap while recovering genuine zombie
# checks in the same operating window instead of leaving them for seven hours.
DEFAULT_STALE_OPENCODE_MINUTES = 90
DEFAULT_UPDATE_BRANCH_HEAD_POLL_ATTEMPTS = 6
DEFAULT_UPDATE_BRANCH_HEAD_POLL_SECONDS = 5.0
OPENCODE_WORKFLOW_NAMES = {
    "OpenCode Review",
    "Required OpenCode Review",
    "OpenCode Review Dispatch",
}
RUNNING_CHECK_STATES = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}
FAILED_CHECK_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE"}
ACTION_REQUIRED_CONCLUSIONS = {"ACTION_REQUIRED"}
GIT_REF_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
GITHUB_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
REVIEW_BODY_HEAD_SHA_RE = re.compile(r"Head SHA:\s*`([0-9a-fA-F]{40})`")
ACTIONS_JOB_DETAILS_URL_RE = re.compile(r"/actions/runs/\d+/job/(\d+)(?:[/?#]|$)")
DIRECT_MERGE_AUTO_FALLBACK_MARKERS = (
    "base branch policy prohibits the merge",
    "is not mergeable",
    "merge requirements",
    "required status check",
)
SQUASH_MERGE_DISABLED_MARKERS = (
    "squash merge is not allowed",
    "squash merges are not allowed",
)
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
REST_MERGEABLE_STATE_WORKERS = 10
DETERMINISTIC_APPROVAL_MARKERS = (
    "deterministic current-head evidence",
    "deterministic fallback approval",
    "did not emit a usable current-head control block",
)
COVERAGE_REVIEW_MARKERS = (
    "coverage evidence did not pass",
    "coverage-evidence",
    "required test/docstring evidence",
)
LAST_PUSH_APPROVAL_RESTAMP_MESSAGE = "chore: refresh head for last-push approval"


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


SENSITIVE_DATA_SCRUB_PATTERNS = (
    (re.compile(r'(?i)(bearer\s+)[^\s"\'\\]+'), r'\1***'),
    (re.compile(r'(?i)(token\s+)[^\s"\'\\]+'), r'\1***'),
    (re.compile(r'(?i)\b(?:github_pat_[A-Za-z0-9_]+|gh[pousr]_[A-Za-z0-9_]+)\b'), '***'),
    (re.compile(r'\b(sk-[A-Za-z0-9_-]+)'), '***'),
    (re.compile(r'\b(xox[baprs]-[A-Za-z0-9-]+)'), '***'),
    (re.compile(r'\b(AKIA[0-9A-Z]{16})'), '***'),
    (re.compile(r'(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|password|passwd|secret)\s*[:=]\s*)["\']?[^"\'\s]+["\']?'), r'\1***'),
    (re.compile(r'(?i)((?:authorization|proxy-authorization)\s*:\s*(?:bearer|basic)\s+)[A-Za-z0-9._~+\/=-]+'), r'\1***'),
)


def scrub_sensitive_data(text: str | None) -> str | None:
    """Mask sensitive tokens in text to prevent secret leakage."""
    if not text:
        return text
    for pattern, repl in SENSITIVE_DATA_SCRUB_PATTERNS:
        text = pattern.sub(repl, text)
    return text


def mutation_token_source() -> str:
    """Return the configured scheduler mutation credential source."""
    return (os.environ.get("SCHEDULER_MUTATION_TOKEN_SOURCE") or "github-token").strip() or "github-token"


def mutation_token_label() -> str:
    """Return a non-secret label for the scheduler mutation credential."""
    source = mutation_token_source()
    labels = {
        "PR_REVIEW_MERGE_TOKEN": "PR_REVIEW_MERGE_TOKEN",
        "OPENCODE_APPROVE_TOKEN": "OPENCODE_APPROVE_TOKEN",
        "opencode-app": "OpenCode app token",
        "github-token": "workflow GITHUB_TOKEN",
    }
    return labels.get(source, "workflow GH_TOKEN")


def mutation_actor_label() -> str:
    """Return the expected GitHub actor class for scheduler mutations."""
    source = mutation_token_source()
    if source == "github-token":
        return "github-actions[bot]"
    if source == "opencode-app":
        return "OpenCode GitHub App"
    return "configured workflow credential"


def contract_decision(decision: Decision) -> str:
    """Map scheduler actions into the bounded PR decision contract."""
    if decision.action in {"update_branch", "restamp_head"}:
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
        guidance: dict[str, Any] = {
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
        changed_files = parse_conflict_changed_files(decision.reason)
        if changed_files:
            guidance["changed_files_to_inspect"] = changed_files
        return guidance
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
    external_merge = parse_external_head_merge_reason(decision.reason)
    if external_merge:
        return {
            "type": "external_head_merge_excluded",
            "head_repository": external_merge,
            "summary": "The PR can be reviewed centrally, but this external head is excluded from scheduler direct merge and auto-merge.",
            "automation_limit": "The scheduler deliberately leaves fork or external-head merges to maintainers even when approval evidence is clean.",
            "next_required_evidence": [
                "same-head OpenCode approval",
                "same-head Strix evidence",
                "required GitHub Checks success",
                "zero active unresolved review threads",
                "maintainer manual merge decision",
            ],
        }
    if parse_last_push_approval_restamp_reason(decision.reason):
        return {
            "type": "last_push_approval_restamp",
            "actor": mutation_actor_label(),
            "token": mutation_token_label(),
            "required_permission": "contents: write",
            "head_guard": "live PR head check plus force=false Git ref update",
            "summary": "GitHub Actions creates a same-tree child commit so require_last_push_approval can be satisfied by a later non-pusher approval.",
            "automation_limit": "The refreshed head is not merge evidence by itself; all current-head checks, Strix evidence, OpenCode review, and review-thread gates must rerun after the new commit.",
            "next_required_evidence": [
                "new same-tree head SHA after the restamp mutation",
                "OpenCode approval on that exact new head",
                "same-head Strix evidence",
                "required GitHub Checks success",
                "zero active unresolved review threads",
                "approving review from an actor who did not push the refreshed head",
            ],
        }
    if decision.action == "update_branch":
        return {
            "type": "github_actions_update_branch",
            "actor": mutation_actor_label(),
            "token": mutation_token_label(),
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
            "actor": mutation_actor_label(),
            "token": mutation_token_label(),
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
    """Run a command and return stdout, raising a scrubbed summary on failure."""
    return run_with_env(args, stdin=stdin)


def run_with_env(args: Sequence[str], *, stdin: str | None = None, env: dict[str, str] | None = None) -> str:
    """Run a command with an optional environment override and scrub failures."""
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
            env=env,
        )
    except subprocess.CalledProcessError as exc:
        scrubbed_args = scrub_sensitive_data(' '.join(argv))
        scrubbed_stderr = scrub_sensitive_data(exc.stderr or "")
        raise RuntimeError(
            f"Command failed ({exc.returncode}): {scrubbed_args}\n{scrubbed_stderr}"
        ) from exc
    return process.stdout


def scheduler_read_env() -> dict[str, str] | None:
    """Return an env override for GitHub read calls when configured."""
    read_token = os.environ.get("SCHEDULER_READ_TOKEN")
    if not read_token or read_token == os.environ.get("GH_TOKEN"):
        return None
    env = os.environ.copy()
    env["GH_TOKEN"] = read_token
    return env


def run_github_read(args: Sequence[str], *, stdin: str | None = None) -> str:
    """Run a GitHub read command with the configured read token when available."""
    env = scheduler_read_env()
    if env is None:
        return run(args, stdin=stdin)
    return run_with_env(args, stdin=stdin, env=env)


def scheduler_actions_env() -> dict[str, str] | None:
    """Return an env override for GitHub Actions control calls when configured."""
    actions_token = os.environ.get("SCHEDULER_ACTIONS_TOKEN")
    if not actions_token or actions_token == os.environ.get("GH_TOKEN"):
        return None
    env = os.environ.copy()
    env["GH_TOKEN"] = actions_token
    return env


def run_github_actions(args: Sequence[str], *, stdin: str | None = None) -> str:
    """Run a GitHub Actions control command with the workflow token when configured."""
    env = scheduler_actions_env()
    if env is None:
        return run(args, stdin=stdin)
    return run_with_env(args, stdin=stdin, env=env)


def scheduler_dispatch_env() -> dict[str, str] | None:
    """Return an env override for central repository dispatch when configured.

    The OpenCode app installation has no Actions permission, so the mutation token
    cannot create a repository dispatch. When the scheduler executes inside the
    central repository receiving the event, the runner's own github.token is a
    sufficient credential; the workflow passes it through SCHEDULER_DISPATCH_TOKEN.
    """
    dispatch_token = os.environ.get("SCHEDULER_DISPATCH_TOKEN")
    if not dispatch_token or dispatch_token == os.environ.get("GH_TOKEN"):
        return None
    env = os.environ.copy()
    env["GH_TOKEN"] = dispatch_token
    return env


def run_github_dispatch(args: Sequence[str], *, stdin: str | None = None) -> str:
    """Run a repository dispatch command with the dispatch token when configured."""
    env = scheduler_dispatch_env()
    if env is None:
        return run_github_actions(args, stdin=stdin)
    return run_with_env(args, stdin=stdin, env=env)


def split_repo(repo: str) -> tuple[str, str]:
    """Split an owner/name repository string into owner and repository name."""
    try:
        owner, name = repo.split("/", 1)
    except ValueError as exc:
        raise ValueError(f"repo must be owner/name, got {repo!r}") from exc
    if not owner or not name:
        raise ValueError(f"repo must be owner/name, got {repo!r}")
    return owner, name


def validate_git_ref(ref: str) -> str:
    """Return a conservative Git ref name for gh workflow dispatch fields."""
    if (
        not isinstance(ref, str)
        or not ref
        or not GIT_REF_RE.fullmatch(ref)
        or ref == "HEAD"
        or ref.startswith("/")
        or ref.endswith(("/", "."))
        or "@{" in ref
        or ".." in ref
        or "//" in ref
    ):
        raise ValueError(f"invalid git ref: {ref!r}")
    if any(part == "." or part.startswith(".") for part in ref.split("/")):
        raise ValueError(f"invalid git ref: {ref!r}")
    return ref


def validate_git_sha(sha: str) -> str:
    """Return a 40-character hex SHA for head-guarded GitHub operations."""
    if not isinstance(sha, str) or not GIT_SHA_RE.fullmatch(sha):
        raise ValueError(f"invalid git sha: {sha!r}")
    return sha


def validate_github_repository(repo: str) -> str:
    """Return a GitHub owner/repository name safe to pass to gh."""
    if not isinstance(repo, str) or not GITHUB_REPOSITORY_RE.fullmatch(repo):
        raise ValueError(f"invalid GitHub repository: {repo!r}")
    return repo


def validated_pr_dispatch_fields(pr: dict[str, Any]) -> tuple[str, str, str]:
    """Return validated base ref, base SHA, and head SHA for workflow dispatch."""
    return (
        validate_git_ref(pr["baseRefName"]),
        validate_git_sha(pr["baseRefOid"]),
        validate_git_sha(pr["headRefOid"]),
    )


def repository_dispatch_target(repo: str) -> str:
    """Return the default-branch repository that receives review dispatch events.

    Organization required workflows are sourced from ContextualWisdomLab/.github,
    while most target repositories deliberately do not keep repo-local workflow
    copies. GitHub evaluates ``repository_dispatch`` only from the receiver's
    default branch, so callers cannot select a privileged workflow ref.
    """
    target_repo = validate_github_repository(repo)
    dispatch_repo = (os.environ.get("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY") or "").strip()
    if not dispatch_repo:
        return target_repo
    return validate_github_repository(dispatch_repo)


def env_flag_enabled(name: str) -> bool:
    """Return whether an environment flag is explicitly truthy."""
    return (os.environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def repository_dispatch_wait_reason(repo: str, workflow: str) -> str | None:
    """Explain why cross-repository required repository dispatch should wait."""
    target_repo = validate_github_repository(repo)
    dispatch_repo = (os.environ.get("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY") or "").strip()
    if not dispatch_repo:
        return None
    dispatch_repo = validate_github_repository(dispatch_repo)
    if dispatch_repo == target_repo or env_flag_enabled("SCHEDULER_ALLOW_CROSS_REPO_REPOSITORY_DISPATCH"):
        return None
    execution_repo = (os.environ.get("GITHUB_REPOSITORY") or "").strip()
    if os.environ.get("SCHEDULER_DISPATCH_TOKEN") and execution_repo == dispatch_repo:
        # The dispatch targets the repository this scheduler run executes in and the
        # workflow provided a dispatch-capable runner token for it, so no
        # cross-repository credential is needed.
        return None
    return (
        f"{workflow} dispatch waits for central required workflow materialization; "
        f"required workflow source is {dispatch_repo}, but this scheduler run has no "
        "cross-repository repository-dispatch credential. Wait for the organization required "
        "workflow to materialize, or rerun the same-head target-repository job after GitHub "
        "exposes it in the PR check rollup."
    )


TRANSIENT_GITHUB_API_ERRORS = (
    "HTTP 500",
    "HTTP 502",
    "HTTP 503",
    "HTTP 504",
    "connection reset",
    "connection refused",
    "connection timed out",
    "context deadline exceeded",
    "gateway timeout",
    "i/o timeout",
    "server error",
    "service unavailable",
    "stream error",
    "temporary failure",
    "timeout",
    "unexpected end of JSON input",
    "unexpected EOF",
    "received from peer",
)


def is_transient_github_api_error(exc: Exception) -> bool:
    """Return whether a GitHub API failure is worth retrying in the same run."""
    if isinstance(exc, json.JSONDecodeError):
        return True
    message = str(exc)
    folded = message.lower()
    return any(marker in message or marker.lower() in folded for marker in TRANSIENT_GITHUB_API_ERRORS)


def gh_graphql(query: str, **fields: str | int) -> dict[str, Any]:
    """Run a GitHub GraphQL query through gh and decode the JSON response."""
    cmd = ["gh", "api", "graphql", "-F", "query=@-"]
    for key, value in fields.items():
        flag = "-F" if isinstance(value, int) else "-f"
        cmd.extend([flag, f"{key}={value}"])
    max_attempts = 4
    for attempt in range(1, max_attempts + 1):  # pragma: no branch - last failed attempt always raises
        try:
            return json.loads(run_github_read(cmd, stdin=query))
        except (RuntimeError, json.JSONDecodeError) as exc:
            if attempt >= max_attempts or not is_transient_github_api_error(exc):
                raise
            delay = min(2 ** (attempt - 1), 8)
            print(
                f"Transient GitHub GraphQL error on attempt {attempt}/{max_attempts}; retrying in {delay}s",
                file=sys.stderr,
            )
            time.sleep(delay)


def github_resource_inaccessible(exc: RuntimeError) -> bool:
    """Return whether GitHub denied an API read for the current integration token."""

    return "Resource not accessible by integration" in str(exc)


def gh_api_json(path: str) -> Any:
    """Run a GitHub REST API request through gh and decode the JSON response."""

    return json.loads(run_github_read(["gh", "api", path]))


def rest_review_node(review: dict[str, Any]) -> dict[str, Any]:
    """Convert a REST review payload into the GraphQL shape used by the scheduler."""

    commit_id = review.get("commit_id")
    return {
        "databaseId": review.get("id"),
        "state": review.get("state"),
        "body": review.get("body"),
        "submittedAt": review.get("submitted_at"),
        "author": {"login": ((review.get("user") or {}).get("login"))},
        "commit": {"oid": commit_id} if commit_id else None,
    }


def rest_check_node(check: dict[str, Any]) -> dict[str, Any]:
    """Convert a REST check-run payload into the GraphQL status rollup shape."""

    return {
        "__typename": "CheckRun",
        "name": check.get("name"),
        "status": (check.get("status") or "").upper(),
        "conclusion": (check.get("conclusion") or "").upper() if check.get("conclusion") else None,
        "startedAt": check.get("started_at"),
        "detailsUrl": check.get("details_url"),
        "checkSuite": {"workflowRun": {"workflow": {}}},
    }


def rest_pr_node(repo: str, pr: dict[str, Any]) -> dict[str, Any]:
    """Convert a REST pull request payload into the GraphQL shape used by the scheduler."""

    number = int(pr["number"])
    head = pr.get("head") or {}
    base = pr.get("base") or {}
    head_repo = head.get("repo") or {}
    reviews = gh_api_json(f"repos/{repo}/pulls/{number}/reviews?per_page=100")
    checks = gh_api_json(f"repos/{repo}/commits/{head.get('sha')}/check-runs?per_page=100")
    files = gh_api_json(f"repos/{repo}/pulls/{number}/files?per_page=20")
    rest_merge_state = REST_MERGEABLE_STATE_MAP.get(
        str(pr.get("mergeable_state") or "").lower(),
        str(pr.get("mergeable_state") or "").upper(),
    )
    return {
        "number": number,
        "title": pr.get("title"),
        "isDraft": bool(pr.get("draft")),
        "mergeable": pr.get("mergeable"),
        "mergeStateStatus": rest_merge_state,
        "reviewDecision": "REVIEW_REQUIRED",
        "baseRefName": base.get("ref"),
        "baseRefOid": base.get("sha"),
        "headRefName": head.get("ref"),
        "headRefOid": head.get("sha"),
        "isCrossRepository": (head_repo.get("full_name") or repo).lower() != repo.lower(),
        "maintainerCanModify": bool(pr.get("maintainer_can_modify")),
        "headRepository": {"nameWithOwner": head_repo.get("full_name") or repo},
        "autoMergeRequest": pr.get("auto_merge"),
        "reviewThreads": {"nodes": []},
        "files": {"nodes": [{"path": file.get("filename")} for file in files if file.get("filename")]},
        "reviews": {"nodes": [rest_review_node(review) for review in reviews]},
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    rest_check_node(check)
                    for check in (checks.get("check_runs") or [])
                ]
            }
        },
        "restMergeableState": rest_merge_state,
    }


def fetch_open_prs_rest(repo: str, max_prs: int, base_branch: str | None = None) -> list[dict[str, Any]]:
    """Fetch open pull requests through REST when GraphQL is unavailable."""

    prs: list[dict[str, Any]] = []
    page = 1
    while len(prs) < max_prs:
        page_size = min(100, max_prs - len(prs))
        path = (
            f"repos/{repo}/pulls?state=open&sort=created&direction=asc"
            f"&per_page={page_size}&page={page}"
        )
        if base_branch:
            path += f"&base={quote(base_branch, safe='')}"
        payload = gh_api_json(path)
        if not payload:
            break
        if len(payload) <= 1:
            prs.extend(rest_pr_node(repo, pr) for pr in payload)  # pragma: no cover
        else:
            max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(payload))
            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                # Keep original API sort order
                prs.extend(list(executor.map(lambda pr: rest_pr_node(repo, pr), payload)))
        if len(payload) < page_size:
            break
        page += 1
    return prs[:max_prs]


def fetch_pr_rest(repo: str, number: int) -> list[dict[str, Any]]:
    """Fetch one pull request through REST when GraphQL is unavailable."""

    pr = gh_api_json(f"repos/{repo}/pulls/{number}")
    return [rest_pr_node(repo, pr)] if pr else []


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
        try:
            payload = gh_graphql(OPEN_PRS_QUERY, **fields)
        except RuntimeError as exc:
            if github_resource_inaccessible(exc) or is_transient_github_api_error(exc):
                return fetch_open_prs_rest(repo, max_prs)
            raise
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
    try:
        payload = gh_graphql(PR_BY_NUMBER_QUERY, owner=owner, name=name, number=number)
    except RuntimeError as exc:
        if github_resource_inaccessible(exc) or is_transient_github_api_error(exc):
            return fetch_pr_rest(repo, number)
        raise
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


def compare_ref_for_pr_head(repo: str, pr: dict[str, Any]) -> str:
    """Return the compare-API head ref for a PR branch."""
    head_ref = pr.get("headRefName") or "HEAD"
    head_repo = (pr.get("headRepository") or {}).get("nameWithOwner")
    if not head_repo or head_repo == repo:
        return head_ref
    head_owner, _ = split_repo(head_repo)
    return f"{head_owner}:{head_ref}"


def fetch_compare_branch_freshness(repo: str, pr: dict[str, Any]) -> dict[str, Any]:
    """Fetch compare evidence showing whether the PR head lacks base commits."""
    base = quote(pr.get("baseRefName") or "base", safe="")
    head = quote(compare_ref_for_pr_head(repo, pr), safe=":")
    return json.loads(
        run(
            [
                "gh",
                "api",
                f"repos/{repo}/compare/{base}...{head}",
            ]
        )
    )


def enrich_rest_mergeable_states(repo: str, prs: list[dict[str, Any]]) -> None:
    """Attach REST mergeability evidence to GraphQL pull request payloads."""

    def enrich(pr: dict[str, Any]) -> None:
        """Attach REST mergeability evidence to one pull request payload."""
        try:
            pr["restMergeableState"] = fetch_rest_mergeable_state(repo, int(pr["number"]))
        except RuntimeError as exc:
            pr["restMergeableStateError"] = bounded_error_summary(str(exc))
        try:
            compare = fetch_compare_branch_freshness(repo, pr)
            pr["compareStatus"] = compare.get("status")
            pr["compareBehindBy"] = compare.get("behind_by")
        except RuntimeError as exc:
            pr["compareBranchFreshnessError"] = bounded_error_summary(str(exc))

    if not prs:
        return

    if len(prs) <= 1:
        for pr in prs:
            enrich(pr)
        return

    max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(prs))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        for _ in executor.map(enrich, prs):
            pass


def effective_merge_state(pr: dict[str, Any]) -> str:
    """Return the safest merge state from GraphQL plus REST mergeability evidence."""
    graph_state = (pr.get("mergeStateStatus") or "").upper()
    rest_state = (pr.get("restMergeableState") or "").upper()
    if rest_state in REST_MERGEABLE_STATES:
        return rest_state
    if graph_state in {"BEHIND", "DIRTY", "CONFLICTING", "UNKNOWN"}:
        return graph_state
    return rest_state or graph_state


def compare_behind_by(pr: dict[str, Any]) -> int:
    """Return the compare API's behind_by count as a safe integer."""
    behind_by = pr.get("compareBehindBy")
    if isinstance(behind_by, int):
        return max(0, behind_by)
    if isinstance(behind_by, str) and behind_by.isdigit():
        return int(behind_by)
    return 0


def branch_outdated_by_base(pr: dict[str, Any], merge_state: str) -> int:
    """Return known count of base commits missing from the PR head."""
    compare_status = (pr.get("compareStatus") or "").lower()
    if merge_state == "BEHIND" or compare_status == "behind":
        return max(1, compare_behind_by(pr))
    return compare_behind_by(pr)


def context_nodes(pr: dict[str, Any]) -> list[dict[str, Any]]:
    """Return status rollup context nodes for a pull request payload."""
    rollup = pr.get("statusCheckRollup") or {}
    contexts = rollup.get("contexts") or {}
    return contexts.get("nodes") or []


def is_opencode_context(node: dict[str, Any]) -> bool:
    """Return whether a check or status context belongs to OpenCode Review."""
    if node.get("__typename") == "CheckRun":
        if (os.environ.get("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY") or "").strip():
            # Central reviews run through repository_dispatch and publish a commit
            # status. Organization required-workflow CheckRuns are deliberately
            # non-authoritative placeholders and must not suppress that dispatch.
            return False
        workflow = (
            ((node.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow")
            or {}
        )
        return node.get("name") == "opencode-review" or workflow.get("name") in OPENCODE_WORKFLOW_NAMES
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


def actions_job_id_from_details_url(value: str | None) -> str | None:
    """Return a GitHub Actions job id from a check-run details URL."""
    if not value:
        return None
    match = ACTIONS_JOB_DETAILS_URL_RE.search(value)
    return match.group(1) if match else None


def matching_actions_job_id(pr: dict[str, Any], predicate: Any) -> str | None:
    """Return the latest matching check-run job id, if GitHub exposed one."""
    for node in reversed(context_nodes(pr)):
        if node.get("__typename") != "CheckRun" or not predicate(node):
            continue
        job_id = actions_job_id_from_details_url(node.get("detailsUrl"))
        if job_id:
            return job_id
    return None


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
    if not head:
        return False
    body_head = review_body_head_sha(review)
    if commit == head:
        return body_head is None or body_head.lower() == head.lower()
    if not commit and body_head is not None:
        return body_head.lower() == head.lower()
    return False


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
    if len(thread_ids) <= 1:
        for thread_id in thread_ids:  # pragma: no cover
            resolve_review_thread(thread_id)  # pragma: no cover
    else:
        max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(thread_ids))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            list(executor.map(resolve_review_thread, thread_ids))
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


def is_legacy_actions_opencode_review(review: dict[str, Any]) -> bool:
    """Return whether a legacy Actions-authored review contains OpenCode evidence."""
    login = review_author_login(review)
    return login in {"github-actions", "github-actions[bot]"} and "opencode" in (
        review.get("body") or ""
    ).lower()


def is_automated_opencode_review(review: dict[str, Any]) -> bool:
    """Return whether a review is OpenCode automation evidence, including legacy writes."""
    return is_opencode_review(review) or is_legacy_actions_opencode_review(review)


def is_deterministic_fallback_approval(review: dict[str, Any]) -> bool:
    """Return whether an old fail-open approval body is not review evidence."""
    if (review.get("state") or "").upper() != "APPROVED":
        return False
    body = (review.get("body") or "").lower()
    return any(marker in body for marker in DETERMINISTIC_APPROVAL_MARKERS)


def has_current_head_deterministic_fallback_approval(pr: dict[str, Any]) -> bool:
    """Return whether OpenCode's latest current-head review is fallback-only."""
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if not is_opencode_review(review):
            continue
        if not review_matches_current_head(review, pr):
            continue
        return is_deterministic_fallback_approval(review)
    return False


def current_head_review_state(pr: dict[str, Any], state: str) -> bool:
    """Return whether OpenCode's latest current-head review has the target state."""
    target_state = state.upper()
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if not is_opencode_review(review):
            continue
        if not review_matches_current_head(review, pr):
            continue
        if target_state == "APPROVED" and is_deterministic_fallback_approval(review):
            return False
        return (review.get("state") or "").upper() == target_state
    return False


def has_current_head_approval(pr: dict[str, Any]) -> bool:
    """Return whether OpenCode approved the exact current head commit."""
    return current_head_review_state(pr, "APPROVED")


def has_current_head_changes_requested(pr: dict[str, Any]) -> bool:
    """Return whether OpenCode requested changes on the exact current head."""
    return current_head_review_state(pr, "CHANGES_REQUESTED")


def current_head_coverage_change_request(pr: dict[str, Any]) -> bool:
    """Return whether the latest current-head request is only a coverage gate."""
    for review in reversed((pr.get("reviews") or {}).get("nodes") or []):
        if not is_opencode_review(review) or not review_matches_current_head(review, pr):
            continue
        if (review.get("state") or "").upper() != "CHANGES_REQUESTED":
            return False
        body = (review.get("body") or "").lower()
        return all(marker in body for marker in COVERAGE_REVIEW_MARKERS)
    return False


def coverage_evidence_state(pr: dict[str, Any]) -> str:
    """Return missing, running, complete, or failed for the latest coverage gate."""
    for node in reversed(context_nodes(pr)):
        name = (node.get("name") or node.get("context") or "").lower()
        if name != "coverage-evidence":
            continue
        status = (node.get("status") or node.get("state") or "").upper()
        if status in RUNNING_CHECK_STATES:
            return "running"
        if node.get("__typename") == "CheckRun":
            return "complete" if (node.get("conclusion") or "").upper() == "SUCCESS" else "failed"
        return "complete" if status == "SUCCESS" else "failed"
    return "missing"


def stale_opencode_change_request_ids(pr: dict[str, Any]) -> list[int]:
    """Return dismissible automated change requests tied to previous heads."""
    review_ids: list[int] = []
    for review in (pr.get("reviews") or {}).get("nodes") or []:
        if (review.get("state") or "").upper() != "CHANGES_REQUESTED":
            continue
        if review_matches_current_head(review, pr):
            continue
        if not is_automated_opencode_review(review):
            continue
        review_id = review.get("databaseId")
        if isinstance(review_id, int) and review_id > 0:
            review_ids.append(review_id)
    return review_ids


def stale_opencode_approval_ids(pr: dict[str, Any]) -> list[int]:
    """Return active automated approvals whose evidence is not for the live head.

    GitHub evaluates the latest review from each author. Older review objects may
    remain ``APPROVED`` after a later same-author review supersedes them, and the
    dismissal API treats those historical objects as no-ops. Inspect only the
    latest OpenCode review per automation identity so cleanup targets effective
    policy state rather than immutable review history.
    """
    latest_by_author: dict[str, dict[str, Any]] = {}
    for review in (pr.get("reviews") or {}).get("nodes") or []:
        if not is_automated_opencode_review(review):
            continue
        latest_by_author[review_author_login(review)] = review

    review_ids: list[int] = []
    for review in latest_by_author.values():
        if (review.get("state") or "").upper() != "APPROVED":
            continue
        if review_matches_current_head(review, pr):
            continue
        review_id = review.get("databaseId")
        if isinstance(review_id, int) and review_id > 0:
            review_ids.append(review_id)
    return review_ids


def dismiss_pull_request_review(
    repo: str,
    number: str,
    review_id: int,
    *,
    message: str,
) -> bool:
    """Dismiss one review and verify GitHub actually changed its state."""
    try:
        run(
            [
                "gh",
                "api",
                "-X",
                "PUT",
                f"repos/{repo}/pulls/{number}/reviews/{review_id}/dismissals",
                "-f",
                f"message={message}",
            ]
        )
        live_state = run_github_read(
            [
                "gh",
                "api",
                f"repos/{repo}/pulls/{number}/reviews/{review_id}",
                "--jq",
                ".state",
            ]
        ).strip().upper()
    except RuntimeError as exc:
        print(
            "::warning::Stale OpenCode review dismissal failed for "
            f"PR #{number} review {review_id}: {scrub_sensitive_data(str(exc))}"
        )
        return False
    if live_state == "DISMISSED":
        return True
    print(
        "::warning::GitHub accepted stale OpenCode review dismissal for "
        f"PR #{number} review {review_id}, but the verified review state is "
        f"{live_state or '<missing>'}; the review remains non-authoritative unless its explicit "
        "Head SHA matches the live PR head."
    )
    return False


def dismiss_stale_opencode_approvals(
    repo: str,
    pr: dict[str, Any],
    *,
    dry_run: bool,
) -> tuple[int, int]:
    """Dismiss latest automated approvals that do not match the exact live head."""
    review_ids = stale_opencode_approval_ids(pr)
    if not review_ids:
        return 0, 0
    if dry_run:
        return len(review_ids), 0

    require_github_actions_mutation_actor("dismiss-stale-opencode-approval")
    repo = validate_github_repository(repo)
    number = str(int(pr["number"]))
    expected_head = validate_git_sha(pr["headRefOid"])
    live_head = run_github_read(
        ["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", ".head.sha"]
    ).strip()
    if live_head != expected_head:
        raise RuntimeError(
            "PR head changed before stale approval dismissal; "
            f"expected {expected_head}, observed {live_head or '<missing>'}"
        )

    dismissed = 0
    for review_id in review_ids:
        message = (
            "Superseded automated OpenCode approval whose explicit review evidence does not match "
            f"exact current head {expected_head}; a fresh current-head review is required."
        )
        if dismiss_pull_request_review(repo, number, review_id, message=message):
            dismissed += 1
    return dismissed, len(review_ids) - dismissed


def stale_approval_cleanup_note(dismissed: int, retained: int, *, dry_run: bool) -> str | None:
    """Render exact stale-approval cleanup evidence for scheduler logs."""
    notes: list[str] = []
    if dismissed:
        verb = "would dismiss" if dry_run else "dismissed"
        notes.append(f"{verb} {dismissed} latest previous-head automated OpenCode approval(s)")
    if retained:
        notes.append(
            f"GitHub retained {retained} stale automated approval(s) after dismissal attempts; "
            "their head evidence remains non-authoritative"
        )
    return "; ".join(notes) if notes else None


def dismiss_stale_opencode_change_requests(repo: str, pr: dict[str, Any], *, dry_run: bool) -> int:
    """Dismiss previous-head automated gates only after exact-head approval."""
    if not has_current_head_approval(pr):
        return 0
    review_ids = stale_opencode_change_request_ids(pr)
    if not review_ids:
        return 0
    if dry_run:
        return len(review_ids)

    require_github_actions_mutation_actor("dismiss-stale-opencode-review")
    repo = validate_github_repository(repo)
    number = str(int(pr["number"]))
    expected_head = validate_git_sha(pr["headRefOid"])
    live_head = run_github_read(
        ["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", ".head.sha"]
    ).strip()
    if live_head != expected_head:
        raise RuntimeError(
            "PR head changed before stale review dismissal; "
            f"expected {expected_head}, observed {live_head or '<missing>'}"
        )

    for review_id in review_ids:
        message = (
            "Superseded automated OpenCode change request from a previous head; "
            f"exact current head {expected_head} has a later OpenCode approval."
        )
        run(
            [
                "gh",
                "api",
                "-X",
                "PUT",
                f"repos/{repo}/pulls/{number}/reviews/{review_id}/dismissals",
                "-f",
                f"message={message}",
            ]
        )
    return len(review_ids)


def failed_status_checks(
    pr: dict[str, Any],
    *,
    ignore_opencode: bool = False,
) -> list[str]:
    """Return failing check or status context names from the PR rollup.

    ``ignore_opencode`` is reserved for the authenticated coverage-only retry
    path: the previous OpenCode run is expected to be failing there because it
    published the current-head coverage change request being retried.
    """
    failed: list[str] = []
    latest_check_runs: dict[
        tuple[str, str],
        tuple[datetime | None, int, dict[str, Any]],
    ] = {}
    status_contexts: list[dict[str, Any]] = []
    for index, node in enumerate(context_nodes(pr)):
        if node.get("__typename") != "CheckRun":
            status_contexts.append(node)
            continue
        workflow = (
            (((node.get("checkSuite") or {}).get("workflowRun") or {}).get("workflow") or {}).get("name")
            or ""
        )
        key = (workflow, node.get("name") or "check-run")
        started_at = parse_github_datetime(node.get("startedAt"))
        previous = latest_check_runs.get(key)
        if previous is None:
            latest_check_runs[key] = (started_at, index, node)
            continue
        previous_started_at, previous_index, _ = previous
        if started_at is None and previous_started_at is not None:
            continue
        if previous_started_at is None and started_at is not None:
            latest_check_runs[key] = (started_at, index, node)
            continue
        if (started_at or datetime.min.replace(tzinfo=timezone.utc), index) >= (
            previous_started_at or datetime.min.replace(tzinfo=timezone.utc),
            previous_index,
        ):
            latest_check_runs[key] = (started_at, index, node)

    successful_status_contexts = {
        node.get("context")
        for node in status_contexts
        if (node.get("state") or "").upper() == "SUCCESS"
    }
    for _, _, node in sorted(latest_check_runs.values(), key=lambda item: item[1]):
        conclusion = (node.get("conclusion") or "").upper()
        if conclusion in FAILED_CHECK_CONCLUSIONS:
            if ignore_opencode and is_opencode_context(node):
                continue
            if is_strix_context(node) and "strix" in successful_status_contexts:
                continue
            if is_opencode_context(node) and "opencode-review" in successful_status_contexts:
                continue
            failed.append(node.get("name") or "check-run")
    for node in status_contexts:
        state = (node.get("state") or "").upper()
        if state in {"FAILURE", "ERROR"}:
            if ignore_opencode and is_opencode_context(node):
                continue
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


def run_head_guarded_merge(
    repo: str,
    number: str,
    head: str,
    *,
    auto: bool,
) -> None:
    """Run a head-guarded merge using an allowed repository merge method."""
    args = ["gh", "pr", "merge", number, "--repo", repo]
    if auto:
        args.append("--auto")
    args.extend(["--squash", "--match-head-commit", head])
    try:
        run(args)
        return
    except RuntimeError as exc:
        detail = str(exc).lower()
        if not any(marker in detail for marker in SQUASH_MERGE_DISABLED_MARKERS):
            raise
        reason = str(exc).splitlines()[-1][:400]

    mode = "auto-merge" if auto else "direct merge"
    print(
        f"PR #{number}: squash is disabled; retrying {mode} with a merge commit "
        f"at guarded head {head}. GitHub reason: {reason}"
    )
    merge_args = ["gh", "pr", "merge", number, "--repo", repo]
    if auto:
        merge_args.append("--auto")
    merge_args.extend(["--merge", "--match-head-commit", head])
    run(merge_args)


def enable_auto_merge(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Enable auto-merge for a PR at its current head using an allowed method."""
    number = str(pr["number"])
    if dry_run:
        return
    require_github_actions_mutation_actor("enable-auto-merge")
    head = validate_git_sha(pr["headRefOid"])
    run_head_guarded_merge(repo, number, head, auto=True)


def merge_pr(repo: str, pr: dict[str, Any], *, dry_run: bool) -> None:
    """Merge a current-head-approved PR immediately with a head guard."""
    number = str(pr["number"])
    if dry_run:
        return
    require_github_actions_mutation_actor("direct-merge")
    head = validate_git_sha(pr["headRefOid"])
    run_head_guarded_merge(repo, number, head, auto=False)


def direct_merge_can_fallback_to_auto_merge(error: Exception) -> bool:
    """Return whether a direct merge failure should queue auto-merge instead."""
    text = str(error).lower()
    return any(marker in text for marker in DIRECT_MERGE_AUTO_FALLBACK_MARKERS)


def direct_merge_block_detail(error: Exception) -> str:
    """Return the concrete GitHub merge refusal detail for scheduler logs."""
    lines = [line.strip() for line in str(error).splitlines() if line.strip()]
    detail_lines = [
        line
        for line in lines
        if line.startswith(("X ", "gh:", "{"))
        or "Repository rule violations found" in line
        or "required" in line.lower()
        or "prohibits the merge" in line.lower()
    ]
    if not detail_lines:
        detail_lines = lines[-2:]
    detail = " ".join(detail_lines)
    return detail[:600] if detail else "GitHub did not return a merge refusal detail"


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
    if dry_run:
        return
    require_github_actions_mutation_actor("update-branch")
    head = validate_git_sha(pr["headRefOid"])
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


def latest_commit_headline(pr: dict[str, Any]) -> str:
    """Return the latest PR commit headline from the GraphQL payload."""
    commits = pr.get("commits") or {}
    nodes = commits.get("nodes") or []
    if not nodes:
        return ""
    commit = nodes[-1].get("commit") or {}
    return str(commit.get("messageHeadline") or "")


def head_already_restamped_for_last_push_approval(pr: dict[str, Any]) -> bool:
    """Return whether the latest PR commit is the scheduler restamp commit."""
    return latest_commit_headline(pr) == LAST_PUSH_APPROVAL_RESTAMP_MESSAGE


def should_restamp_for_last_push_approval(
    repo: str,
    pr: dict[str, Any],
    merge_state: str,
    *,
    current_head_approved: bool,
    auto_merge_enabled: bool,
) -> bool:
    """Return whether a BLOCKED approved PR likely needs a last-push approval restamp."""
    if merge_state != "BLOCKED":
        return False
    if not current_head_approved or not auto_merge_enabled:
        return False
    if not same_repository_head(repo, pr):
        return False
    if str(pr.get("reviewDecision") or "").upper() != "APPROVED":
        return False
    if strix_evidence_state(pr) != "complete":
        return False
    return branch_outdated_by_base(pr, merge_state) == 0


def last_push_approval_block_reason() -> str:
    """Return the explicit scheduler reason for suspected last-push approval blocking."""
    return (
        "current head is approved and auto-merge is queued, but GitHub mergeability is BLOCKED "
        "while reviewDecision is APPROVED; likely require_last_push_approval cannot be satisfied "
        "by the actor who pushed the current head"
    )


def restamp_pr_head_for_last_push_approval(repo: str, pr: dict[str, Any], *, dry_run: bool) -> str | None:
    """Create a same-tree child commit and move the PR head with a force=false ref update."""
    if dry_run:
        return None
    require_github_actions_mutation_actor("last-push-approval-head-refresh")
    repo = validate_github_repository(repo)
    if not same_repository_head(repo, pr):
        raise RuntimeError("last-push approval head refresh only supports same-repository PR heads")

    number = str(int(pr["number"]))
    head = validate_git_sha(pr["headRefOid"])
    head_ref = validate_git_ref(pr["headRefName"])
    live_head = run(["gh", "api", f"repos/{repo}/pulls/{number}", "--jq", ".head.sha"]).strip()
    if live_head != head:
        raise RuntimeError(
            "PR head changed before last-push approval head refresh; "
            f"expected {head}, observed {live_head or '<missing>'}"
        )

    current_commit = json.loads(run(["gh", "api", f"repos/{repo}/git/commits/{head}"]))
    tree = current_commit.get("tree") or {}
    tree_sha = validate_git_sha(str(tree.get("sha") or ""))
    created_commit = json.loads(
        run(
            ["gh", "api", "-X", "POST", f"repos/{repo}/git/commits", "--input", "-"],
            stdin=json.dumps(
                {
                    "message": LAST_PUSH_APPROVAL_RESTAMP_MESSAGE,
                    "tree": tree_sha,
                    "parents": [head],
                }
            ),
        )
    )
    new_head = validate_git_sha(str(created_commit.get("sha") or ""))
    run(
        ["gh", "api", "-X", "PATCH", f"repos/{repo}/git/refs/heads/{head_ref}", "--input", "-"],
        stdin=json.dumps({"sha": new_head, "force": False}),
    )
    return new_head


def short_sha(value: str | None) -> str:
    """Return a compact SHA for human-readable scheduler notes."""
    if not value:
        return "<unknown>"
    return value[:12]


def wait_for_updated_branch_head(
    repo: str,
    pr: dict[str, Any],
    *,
    attempts: int = DEFAULT_UPDATE_BRANCH_HEAD_POLL_ATTEMPTS,
    delay_seconds: float = DEFAULT_UPDATE_BRANCH_HEAD_POLL_SECONDS,
) -> dict[str, Any] | None:
    """Poll GitHub after update-branch until the PR head or freshness evidence changes."""
    original_head = str(pr.get("headRefOid") or "")
    attempts = max(1, attempts)
    for attempt in range(attempts):
        if attempt and delay_seconds > 0:
            time.sleep(delay_seconds)
        fresh_prs = fetch_pr(repo, int(pr["number"]))
        if not fresh_prs:
            continue
        fresh_pr = fresh_prs[0]
        fresh_head = str(fresh_pr.get("headRefOid") or "")
        if fresh_head and fresh_head != original_head:
            return fresh_pr
        fresh_merge_state = effective_merge_state(fresh_pr)
        if branch_outdated_by_base(fresh_pr, fresh_merge_state) <= 0:
            return fresh_pr
    return None


def post_update_branch_followup(
    repo: str,
    pr: dict[str, Any],
    *,
    dry_run: bool,
    trigger_reviews: bool,
    review_dispatch_allowed: bool,
    workflow: str,
    security_workflow: str,
    stale_opencode_minutes: int,
) -> str | None:
    """After update-branch, observe the new head and dispatch current-head evidence."""
    if dry_run:
        return None

    original_head = str(pr.get("headRefOid") or "")
    updated_pr = wait_for_updated_branch_head(repo, pr)
    if updated_pr is None:
        return (
            "update-branch was accepted, but the scheduler did not observe a refreshed PR head within "
            "the poll window; the next scheduler run must re-read the PR before review or merge"
        )

    updated_head = str(updated_pr.get("headRefOid") or "")
    if not updated_head or updated_head == original_head:
        return (
            f"update-branch completed without a new head SHA (still {short_sha(original_head)}); "
            "wait for GitHub to refresh branch-freshness and required-check evidence"
        )

    dismissed_approvals, retained_approvals = dismiss_stale_opencode_approvals(
        repo,
        updated_pr,
        dry_run=dry_run,
    )
    cleanup_note = stale_approval_cleanup_note(
        dismissed_approvals,
        retained_approvals,
        dry_run=dry_run,
    )
    head_note = f"updated head {short_sha(updated_head)} observed after update-branch"
    if cleanup_note:
        head_note = f"{head_note}; {cleanup_note}"
    if not trigger_reviews:
        return f"{head_note}; review dispatch is disabled for this scheduler run"
    if not review_dispatch_allowed:
        return f"{head_note}; review dispatch limit reached, so no same-head evidence workflow was dispatched"

    strix_state = strix_evidence_state(updated_pr)
    if strix_state == "missing":
        wait_reason = repository_dispatch_wait_reason(repo, security_workflow)
        if wait_reason:
            return f"{head_note}; {wait_reason}"
        dispatch_strix_evidence(repo, security_workflow, updated_pr, dry_run=dry_run)
        return (
            f"{head_note}; same-head Strix evidence dispatched because workflow-token branch updates "
            "must not rely on a PR synchronize event to rerun evidence"
        )
    if strix_state == "running":
        return f"{head_note}; same-head Strix evidence is already running"

    opencode_state = opencode_progress_state(updated_pr, stale_after_minutes=stale_opencode_minutes)
    if opencode_state == "running":
        return f"{head_note}; same-head OpenCode review is already running"

    wait_reason = repository_dispatch_wait_reason(repo, workflow)
    if wait_reason:
        return f"{head_note}; {wait_reason}"
    dispatch_result = dispatch_opencode_review(repo, workflow, updated_pr, dry_run=dry_run)
    if dispatch_result == "already_running":
        return f"{head_note}; same-head OpenCode workflow run is already active"
    return f"{head_note}; same-head Strix evidence is complete, so OpenCode review was dispatched"


def same_repository_head(repo: str, pr: dict[str, Any]) -> bool:
    """Return whether the PR head branch belongs to the repository being scanned."""
    head_repo = (pr.get("headRepository") or {}).get("nameWithOwner")
    return head_repo == repo


def can_update_pr_head(repo: str, pr: dict[str, Any]) -> bool:
    """Return whether the scheduler may try to mutate the PR head branch."""
    if same_repository_head(repo, pr):
        return True
    return bool(pr.get("maintainerCanModify"))


def external_head_merge_reason(repo: str, pr: dict[str, Any]) -> str:
    """Explain why the scheduler will not merge or auto-merge an external PR head."""
    head_repo = (pr.get("headRepository") or {}).get("nameWithOwner") or "<unknown>"
    return (
        f"current-head OpenCode review approved, but head repo {head_repo} is external; "
        "fork or external PR heads are excluded from scheduler direct merge and auto-merge. "
        "A maintainer must merge manually after required checks, same-head OpenCode approval, "
        "same-head Strix evidence, and unresolved-thread checks stay clean"
    )


def non_mutable_head_reason(repo: str, pr: dict[str, Any]) -> str:
    """Explain why a PR can be reviewed but not mechanically updated."""
    head_repo = (pr.get("headRepository") or {}).get("nameWithOwner") or "<unknown>"
    if same_repository_head(repo, pr):
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
            "so the workflow mutation credential performs the guarded GitHub mutation"
        )
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError(
            f"{action} refused without GH_TOKEN; configure the scheduler job to pass "
            "PR_REVIEW_MERGE_TOKEN, OPENCODE_APPROVE_TOKEN, an OpenCode app token, or github.token through GH_TOKEN"
        )


def require_github_actions_control_actor(action: str) -> None:
    """Refuse Actions rerun or dispatch calls without a workflow control token."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError(
            f"{action} refused outside GitHub Actions; dispatch PR Review Merge Scheduler "
            "so the workflow actions credential performs the guarded GitHub Actions control call"
        )
    if not os.environ.get("SCHEDULER_ACTIONS_TOKEN") and not os.environ.get("GH_TOKEN"):
        raise RuntimeError(
            f"{action} refused without SCHEDULER_ACTIONS_TOKEN or GH_TOKEN; configure the scheduler "
            "job to pass github.token through SCHEDULER_ACTIONS_TOKEN for workflow rerun and dispatch calls"
        )


def rerun_actions_job(repo: str, job_id: str, *, dry_run: bool, action: str) -> None:
    """Ask GitHub Actions to rerun an existing required-workflow job."""
    if dry_run:
        return
    require_github_actions_control_actor(action)
    run_github_actions(["gh", "api", "-X", "POST", f"repos/{repo}/actions/jobs/{job_id}/rerun"])


def active_workflow_runs(repo: str, statuses: Sequence[str] = ("queued", "in_progress")) -> list[dict[str, Any]]:
    """Return active workflow runs for a repository."""
    runs: list[dict[str, Any]] = []
    for status in statuses:
        payload = json.loads(
            run_github_actions(
                [
                    "gh",
                    "api",
                    "--method",
                    "GET",
                    f"repos/{repo}/actions/runs",
                    "-f",
                    f"status={status}",
                    "-F",
                    "per_page=100",
                ]
            )
        )
        runs.extend(payload.get("workflow_runs") or [])
    return runs


def workflow_run_mentions_pr(run_data: dict[str, Any], pr_number: int) -> bool:
    """Return whether a workflow run is attached to the pull request number."""
    return any(pr.get("number") == pr_number for pr in run_data.get("pull_requests") or [])


def stale_pr_run_ids(
    repo: str,
    pr: dict[str, Any],
    *,
    workflow: str | None = None,
    statuses: Sequence[str] = ("queued", "in_progress"),
) -> list[str]:
    """Return active run ids for older heads of the same pull request."""
    head = str(pr.get("headRefOid") or "").lower()
    number = int(pr["number"])
    stale: list[str] = []
    for run_data in active_workflow_runs(repo, statuses):
        if workflow is not None and run_data.get("name") != workflow:
            continue
        if str(run_data.get("head_sha") or "").lower() == head:
            continue
        if not workflow_run_mentions_pr(run_data, number):
            continue
        run_id = run_data.get("id")
        if run_id:
            stale.append(str(run_id))
    return stale


def stale_opencode_run_ids(repo: str, workflow: str, pr: dict[str, Any]) -> list[str]:
    """Return active OpenCode run ids for older heads of the same pull request."""
    _, stale = active_opencode_run_ids(repo, workflow, pr)
    return stale


def active_review_run_refs(
    repo: str,
    workflow: str,
    pr: dict[str, Any],
    *,
    run_title: str,
    workflow_aliases: frozenset[str],
    statuses: Sequence[str] = ("queued", "in_progress"),
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return repository-qualified current and stale review workflow runs."""
    target_repo = validate_github_repository(repo)
    dispatch_repo = repository_dispatch_target(target_repo)
    centralized_dispatch = bool(
        (os.environ.get("SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY") or "").strip()
    )
    head = str(pr.get("headRefOid") or "").lower()
    number = int(pr["number"])
    dispatch_title_prefixes = tuple(
        f"{title} {target_repo}#{number}@"
        for title in sorted({run_title, *workflow_aliases}, key=len, reverse=True)
    )
    current: list[tuple[str, str]] = []
    stale: list[tuple[str, str]] = []

    # Only the repository_dispatch receiver hosts the privileged review run.
    # When organization required workflows are materialized in a target
    # repository, their pull_request_target jobs are evidence placeholders and
    # must not suppress the central authenticated reviewer.
    for run_repo in (dispatch_repo,):
        for run_data in active_workflow_runs(run_repo, statuses):
            run_name = str(run_data.get("name") or "")
            if run_name != workflow and run_name not in workflow_aliases:
                continue
            run_id = run_data.get("id")
            if not run_id:
                continue
            run_ref = (run_repo, str(run_id))
            display_title = str(run_data.get("display_title") or "")
            dispatch_title_prefix = next(
                (
                    prefix
                    for prefix in dispatch_title_prefixes
                    if display_title.startswith(prefix)
                ),
                None,
            )
            if run_data.get("event") == "repository_dispatch" and dispatch_title_prefix:
                dispatched_head = display_title.removeprefix(dispatch_title_prefix).lower()
                if not GIT_SHA_RE.fullmatch(dispatched_head):
                    continue
                (current if dispatched_head == head else stale).append(run_ref)
                continue
            if centralized_dispatch:
                continue
            run_head = str(run_data.get("head_sha") or "").lower()
            pull_requests = run_data.get("pull_requests") or []
            if run_head == head:
                if pull_requests and not workflow_run_mentions_pr(run_data, number):
                    continue
                current.append(run_ref)
                continue
            if workflow_run_mentions_pr(run_data, number):
                stale.append(run_ref)
    return current, stale


def active_opencode_run_refs(
    repo: str,
    workflow: str,
    pr: dict[str, Any],
    statuses: Sequence[str] = ("queued", "in_progress"),
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Return repository-qualified current and stale OpenCode run references.

    A central ``repository_dispatch`` run executes at the receiver's default
    branch SHA, not the target pull request SHA. Its protected workflow run-name
    therefore carries the live-validated target repository, PR number, and head
    SHA. Inspect both the target and central repositories so a scheduler pass can
    suppress the same-head retry and cancel an older-head central run safely.
    """
    return active_review_run_refs(
        repo,
        workflow,
        pr,
        run_title="Required OpenCode Review",
        workflow_aliases=frozenset(OPENCODE_WORKFLOW_NAMES),
        statuses=statuses,
    )


def active_opencode_run_ids(
    repo: str,
    workflow: str,
    pr: dict[str, Any],
    statuses: Sequence[str] = ("queued", "in_progress"),
) -> tuple[list[str], list[str]]:
    """Return current-head and stale OpenCode run ids for one pull request.

    A repository-dispatch run can have an empty ``pull_requests`` array even
    though its validated inputs target a PR. Treat a matching OpenCode workflow
    name plus the exact current head SHA as sufficient current-head ownership;
    otherwise require an explicit PR association before classifying a run as
    stale. This prevents repeated scheduler passes from dispatching a new run
    that cancels the already queued or running same-head review.
    """
    current, stale = active_opencode_run_refs(repo, workflow, pr, statuses)
    return [run_id for _, run_id in current], [run_id for _, run_id in stale]


def force_cancel_workflow_runs(repo: str, run_ids: Sequence[str]) -> dict[str, str]:
    """Force-cancel workflow runs without blocking current-head decisions."""
    if not run_ids:
        return {}

    def cancel_one(run_id: str) -> tuple[str, str | None]:
        """Return one run id and its bounded GitHub cancellation error, if any."""
        try:
            run_github_actions(
                [
                    "gh",
                    "api",
                    "-X",
                    "POST",
                    f"repos/{repo}/actions/runs/{run_id}/force-cancel",
                ]
            )
        except RuntimeError as exc:
            return run_id, str(exc).replace("\n", "; ")[:600]
        return run_id, None

    if len(run_ids) == 1:
        results = [cancel_one(str(run_ids[0]))]
    else:
        max_workers = min(REST_MERGEABLE_STATE_WORKERS, len(run_ids))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(cancel_one, (str(run_id) for run_id in run_ids)))

    failures = {run_id: reason for run_id, reason in results if reason is not None}
    for run_id, reason in failures.items():
        print(
            "::warning::Could not force-cancel superseded workflow run "
            f"{run_id}: {reason}. Continuing current-head processing; "
            "the old-head run remains non-authoritative."
        )
    return failures


def force_cancel_workflow_run_refs(run_refs: Sequence[tuple[str, str]]) -> None:
    """Force-cancel repository-qualified runs while retaining bounded batches."""
    runs_by_repo: dict[str, list[str]] = {}
    for run_repo, run_id in run_refs:
        runs_by_repo.setdefault(run_repo, []).append(run_id)
    for run_repo, run_ids in runs_by_repo.items():
        force_cancel_workflow_runs(run_repo, run_ids)


def cancel_stale_pr_runs(repo: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel queued or running workflows for older heads of the same PR."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-pr-runs")
    run_ids = stale_pr_run_ids(repo, pr)
    force_cancel_workflow_runs(repo, run_ids)
    return run_ids


def cancel_stale_opencode_runs(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> list[str]:
    """Force-cancel older OpenCode runs for the same PR before retrying current head."""
    if dry_run:
        return []
    require_github_actions_control_actor("force-cancel-stale-opencode-review")
    _, stale_refs = active_opencode_run_refs(repo, workflow, pr)
    force_cancel_workflow_run_refs(stale_refs)
    return [run_id for _, run_id in stale_refs]


def dispatch_opencode_review(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> str:
    """Dispatch trusted OpenCode for the PR head, or report an active run.

    The review job is intentionally restricted to ``repository_dispatch``. A
    check-run job exposed by the original ``pull_request_target`` workflow is
    therefore not a reusable execution entrypoint: rerunning that job preserves
    the original event and leaves the review job skipped. Always use the
    default-branch dispatch entrypoint after same-head deduplication.
    """
    if not dry_run:
        require_github_actions_control_actor("inspect-active-opencode-review")
        current_run_refs, stale_run_refs = active_opencode_run_refs(repo, workflow, pr)
        force_cancel_workflow_run_refs(stale_run_refs)
        if current_run_refs:
            print(
                "OpenCode review dispatch skipped: active same-head workflow run(s) "
                + ", ".join(
                    f"{run_repo}@{run_id}" for run_repo, run_id in current_run_refs
                )
            )
            return "already_running"
    if dry_run:
        return "dry_run"
    base_ref, base_sha, head_sha = validated_pr_dispatch_fields(pr)
    head_ref = validate_git_ref(pr["headRefName"])
    target_repo = validate_github_repository(repo)
    dispatch_repo = repository_dispatch_target(target_repo)
    run_github_dispatch(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{dispatch_repo}/dispatches",
            "--input",
            "-",
        ],
        stdin=json.dumps(
            {
                "event_type": "opencode-review",
                "client_payload": {
                    "target_repository": target_repo,
                    "pr_number": int(pr["number"]),
                    "pr_base_ref": base_ref,
                    "pr_base_sha": base_sha,
                    "pr_head_ref": head_ref,
                    "pr_head_sha": head_sha,
                },
            }
        ),
    )
    return "dispatched"


def dispatch_strix_evidence(repo: str, workflow: str, pr: dict[str, Any], *, dry_run: bool) -> str:
    """Dispatch same-head Strix workflow evidence before OpenCode reviews."""
    job_id = matching_actions_job_id(pr, is_strix_context)
    if job_id:
        rerun_actions_job(repo, job_id, dry_run=dry_run, action="rerun-strix-evidence")
        return "rerun" if not dry_run else "dry_run"
    if dry_run:
        return "dry_run"
    require_github_actions_control_actor("inspect-active-strix-evidence")
    current_run_refs, stale_run_refs = active_review_run_refs(
        repo,
        workflow,
        pr,
        run_title="Strix Security Scan",
        workflow_aliases=frozenset({"Strix Security Scan"}),
    )
    force_cancel_workflow_run_refs(stale_run_refs)
    if current_run_refs:
        print(
            "Strix evidence dispatch skipped: active same-head workflow run(s) "
            + ", ".join(
                f"{run_repo}@{run_id}" for run_repo, run_id in current_run_refs
            )
        )
        return "already_running"
    base_ref, base_sha, head_sha = validated_pr_dispatch_fields(pr)
    target_repo = validate_github_repository(repo)
    dispatch_repo = repository_dispatch_target(target_repo)
    run_github_dispatch(
        [
            "gh",
            "api",
            "-X",
            "POST",
            f"repos/{dispatch_repo}/dispatches",
            "--input",
            "-",
        ],
        stdin=json.dumps(
            {
                "event_type": "strix-scan",
                "client_payload": {
                    "target_repository": target_repo,
                    "pr_number": int(pr["number"]),
                    "pr_base_ref": base_ref,
                    "pr_base_sha": base_sha,
                    "pr_head_sha": head_sha,
                },
            }
        ),
    )
    return "dispatched"


def merge_conflict_guidance(pr: dict[str, Any], merge_state: str) -> str:
    """Return actionable conflict repair guidance for a conflicting PR."""
    base_ref = pr.get("baseRefName") or "base"
    head_ref = pr.get("headRefName") or "head"
    changed_files = conflict_changed_files_text(pr)
    changed_files_note = (
        f"changed files to inspect first: {changed_files}; "
        if changed_files
        else ""
    )
    return (
        f"merge conflict: {merge_state}; base={base_ref}, head={head_ref}; "
        f"{changed_files_note}"
        f"run `gh pr checkout {pr.get('number', '<pr>')}`, `git fetch origin {base_ref}`, then "
        f"`git merge --no-ff origin/{base_ref}` or `git rebase origin/{base_ref}`; "
        "use `git status --short` to find conflicted files, resolve conflict markers in the PR branch, "
        f"rerun focused checks, and push the same {head_ref} branch "
        "(use `git push --force-with-lease` only if rebased); "
        "do not retry update-branch until the conflict is repaired"
    )


def changed_file_paths(pr: dict[str, Any], *, limit: int = 10) -> list[str]:
    """Return changed file paths already present in the pull request payload."""
    nodes = ((pr.get("files") or {}).get("nodes") or [])[:limit]
    return [path for node in nodes if isinstance(path := node.get("path"), str) and path]


def conflict_changed_files_text(pr: dict[str, Any], *, limit: int = 10) -> str:
    """Return compact changed-file guidance for conflict repair text."""
    paths = changed_file_paths(pr, limit=limit)
    if not paths:
        return ""
    total = len(((pr.get("files") or {}).get("nodes") or []))
    suffix = f" | +{total - len(paths)} more" if total > len(paths) else ""
    return " | ".join(paths) + suffix


def auto_merge_wait_reason(merge_state: str, pr: dict[str, Any] | None = None) -> str:
    """Explain why an approved PR with auto-merge enabled is still waiting."""
    if merge_state == "CLEAN":
        return "current head is approved; auto-merge already enabled"
    if merge_state in {"DIRTY", "CONFLICTING"}:
        return (
            "current head is approved and auto-merge is already enabled, "
            "but conflict repair is required before GitHub can merge it"
        )
    review_decision = str((pr or {}).get("reviewDecision") or "").upper()
    review_policy_note = ""
    if merge_state == "BLOCKED" and review_decision and review_decision != "APPROVED":
        review_policy_note = (
            f" and GitHub reviewDecision is {review_decision}; required approving review, "
            "code-owner review, or last-push approval policy is still unsatisfied"
        )
    return (
        "current head is approved and auto-merge is already enabled, "
        f"but GitHub mergeability is {merge_state}{review_policy_note}; wait for required workflows, rulesets, "
        "or branch freshness to clear, then rerun the scheduler if GitHub does not merge it"
    )


def current_head_can_attempt_merge(pr: dict[str, Any], merge_state: str) -> bool:
    """Return whether GitHub currently reports policy-clean mergeability."""
    if merge_state in {"DIRTY", "CONFLICTING", "UNKNOWN"}:
        return False
    if merge_state == "CLEAN":
        return True
    return False


def inspect_pr(
    repo: str,
    pr: dict[str, Any],
    *,
    dry_run: bool,
    trigger_reviews: bool,
    review_dispatch_allowed: bool = True,
    branch_update_allowed: bool = True,
    branch_update_limit: int = 1,
    enable_auto_merge_flag: bool,
    update_branches: bool,
    workflow: str,
    security_workflow: str,
    base_branch: str,
    merge_mode: str = "direct_or_auto",
    stale_opencode_minutes: int = DEFAULT_STALE_OPENCODE_MINUTES,
) -> Decision:
    """Decide and optionally act on one pull request's merge-readiness state."""
    number = pr["number"]
    base_ref = pr.get("baseRefName")

    if pr.get("isDraft"):
        return Decision(number, "skip", "draft PR")
    cancel_stale_pr_runs(repo, pr, dry_run=dry_run)
    if base_ref != base_branch:
        # Stacked/cascade PR (base is another feature branch). Org required
        # workflows are only injected for default-branch-target PRs, so these
        # PRs never receive an OpenCode review on their own — dispatch one here.
        # Merge automation stays default-branch-only; rulesets do not gate
        # feature-branch merges.
        opencode_state = opencode_progress_state(pr, stale_after_minutes=stale_opencode_minutes)
        if opencode_state in {"absent", "stale"} and trigger_reviews and review_dispatch_allowed:
            wait_reason = repository_dispatch_wait_reason(repo, workflow)
            if wait_reason:
                return Decision(number, "wait", f"stacked PR onto {base_ref}; {wait_reason}")
            dispatch_result = dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
            if dispatch_result == "already_running":
                return Decision(
                    number,
                    "wait",
                    f"stacked PR onto {base_ref}; same-head OpenCode workflow run is already active",
                )
            return Decision(
                number,
                "review_dispatch",
                f"stacked PR onto {base_ref}; OpenCode review dispatched",
            )
        return Decision(
            number,
            "skip",
            f"stacked PR onto {base_ref}; OpenCode review {opencode_state}",
        )

    outdated_cleanup_count = resolve_outdated_review_threads(pr, dry_run=dry_run)
    stale_review_cleanup_count = 0
    stale_approval_cleanup_count, retained_stale_approval_count = dismiss_stale_opencode_approvals(
        repo,
        pr,
        dry_run=dry_run,
    )

    def finish(decision: Decision) -> Decision:
        """Attach obsolete review cleanup evidence to the final decision."""
        decision = with_outdated_thread_cleanup_note(
            decision,
            outdated_cleanup_count,
            dry_run=dry_run,
        )
        if stale_review_cleanup_count:
            verb = "Would dismiss" if dry_run else "Dismissed"
            note = (
                f"{verb} {stale_review_cleanup_count} previous-head automated OpenCode "
                "change-request review(s); exact-current-head approval supersedes those stale gates."
            )
            decision = Decision(
                decision.pr,
                decision.action,
                decision.reason,
                (*decision.notes, note),
            )
        approval_note = stale_approval_cleanup_note(
            stale_approval_cleanup_count,
            retained_stale_approval_count,
            dry_run=dry_run,
        )
        if approval_note:
            decision = Decision(
                decision.pr,
                decision.action,
                decision.reason,
                (*decision.notes, approval_note),
            )
        return decision

    def decide(action: str, reason: str) -> Decision:
        """Create a decision after applying shared cleanup notes."""
        return finish(Decision(number, action, reason))

    def request_branch_update(freshness_reason: str, *, suffix: str = "") -> Decision:
        """Request update-branch and attach any same-head evidence follow-up."""
        if not branch_update_allowed:
            return decide(
                "wait",
                f"branch update limit reached ({branch_update_limit} update/run); "
                "defer outdated branch to the next scheduler run",
            )
        update_branch(repo, pr, dry_run=dry_run)
        followup_note = post_update_branch_followup(
            repo,
            pr,
            dry_run=dry_run,
            trigger_reviews=trigger_reviews,
            review_dispatch_allowed=review_dispatch_allowed,
            workflow=workflow,
            security_workflow=security_workflow,
            stale_opencode_minutes=stale_opencode_minutes,
        )
        decision = Decision(
            number,
            "update_branch",
            f"{freshness_reason}; branch update requested with {mutation_token_label()} "
            f"inside GitHub Actions as {mutation_actor_label()}{suffix}",
            (followup_note,) if followup_note else (),
        )
        return finish(decision)

    merge_state = effective_merge_state(pr)
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
        behind_by = branch_outdated_by_base(pr, merge_state)
        if (
            merge_state not in {"DIRTY", "CONFLICTING"}
            and behind_by
            and not pr.get("autoMergeRequest")
            and update_branches
            and trigger_reviews
            and review_dispatch_allowed
            and can_update_pr_head(repo, pr)
        ):
            return request_branch_update(
                "current-head OpenCode review requested changes; branch is outdated before re-review"
            )
        coverage_ready = (
            trigger_reviews
            and review_dispatch_allowed
            and current_head_coverage_change_request(pr)
            and coverage_evidence_state(pr) == "complete"
            and strix_evidence_state(pr) == "complete"
            and not failed_status_checks(pr, ignore_opencode=True)
        )
        if coverage_ready:
            wait_reason = repository_dispatch_wait_reason(repo, workflow)
            if wait_reason:
                return decide("wait", wait_reason)
            dispatch_result = dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
            if dispatch_result == "already_running":
                return decide(
                    "wait",
                    "current-head coverage evidence is complete, but a same-head OpenCode workflow run is already active",
                )
            return decide(
                "review_dispatch",
                "current-head OpenCode coverage blocker is cleared; same-head OpenCode re-dispatched",
            )
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
        stale_review_cleanup_count = dismiss_stale_opencode_change_requests(
            repo,
            pr,
            dry_run=dry_run,
        )
    auto_merge_enabled = bool(pr.get("autoMergeRequest"))
    if merge_state in {"DIRTY", "CONFLICTING"}:
        conflict_reason = merge_conflict_guidance(pr, merge_state)
        if current_head_approved:
            if auto_merge_enabled:
                return finish(
                    disable_auto_merge_decision(
                        repo,
                        pr,
                        dry_run=dry_run,
                        reason=(
                            "current head is approved but merge conflict repair is required before auto-merge "
                            f"can be queued; {conflict_reason}"
                        ),
                    )
                )
            if not same_repository_head(repo, pr):
                return decide("wait", f"{external_head_merge_reason(repo, pr)}; {conflict_reason}")
            return decide(
                "block",
                "current head is approved, but auto-merge is not queued until merge conflict repair is pushed; "
                f"{conflict_reason}",
            )
        if auto_merge_enabled:
            return finish(
                disable_auto_merge_decision(
                    repo,
                    pr,
                    dry_run=dry_run,
                    reason=(
                        f"{conflict_reason}; current head has no OpenCode approval; "
                        "repair the conflict and get same-head approval before re-enabling auto-merge"
                    ),
                )
            )
        return decide("block", conflict_reason)

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

    merge_before_update = current_head_can_attempt_merge(pr, merge_state) and (
        merge_state == "CLEAN" or merge_mode in {"direct", "direct_or_auto"}
    )
    if current_head_approved and merge_before_update:
        if not same_repository_head(repo, pr):
            return decide("wait", external_head_merge_reason(repo, pr))
        if not enable_auto_merge_flag:
            if pr.get("autoMergeRequest"):
                return decide("wait", auto_merge_wait_reason(merge_state, pr))
            return decide("wait", "current head is approved; auto-merge disabled by scheduler inputs")
        if merge_mode == "disabled":
            if pr.get("autoMergeRequest"):
                return decide("wait", auto_merge_wait_reason(merge_state, pr))
            return decide("wait", "current head is approved; merge mode disabled by scheduler inputs")
        if merge_mode in {"direct", "direct_or_auto"}:
            try:
                merge_pr(repo, pr, dry_run=dry_run)
            except RuntimeError as exc:
                if merge_mode != "direct_or_auto" or not direct_merge_can_fallback_to_auto_merge(exc):
                    raise
                block_detail = direct_merge_block_detail(exc)
                if pr.get("autoMergeRequest"):
                    return decide(
                        "auto_merge",
                        "current head is approved; direct merge was blocked by branch policy, "
                        "so the existing auto-merge request remains queued with the same head guard evidence; "
                        f"GitHub reported: {block_detail}",
                    )
                enable_auto_merge(repo, pr, dry_run=dry_run)
                return decide(
                    "auto_merge",
                    "current head is approved; direct merge was blocked by branch policy, "
                    "so auto-merge was enabled with the same head guard evidence; "
                    f"GitHub reported: {block_detail}",
                )
            state_note = "" if merge_state == "CLEAN" else f"; GitHub mergeability is {merge_state}"
            return decide(
                "merge",
                f"current head is approved; direct merge requested with {mutation_token_label()} "
                f"and --match-head-commit{state_note}",
            )
        if merge_mode != "auto":
            return decide("wait", f"current head is approved; unsupported merge mode: {merge_mode}")
        if pr.get("autoMergeRequest"):
            return decide("wait", auto_merge_wait_reason(merge_state, pr))
        enable_auto_merge(repo, pr, dry_run=dry_run)
        return decide("auto_merge", "current head is approved; auto-merge enabled")

    behind_by = branch_outdated_by_base(pr, merge_state)
    if behind_by and (current_head_approved or auto_merge_enabled):
        if not update_branches:
            if current_head_approved:
                return decide("wait", "current-head OpenCode review approved; branch update disabled")
            return decide("wait", "auto-merge already enabled; branch update disabled")
        if not can_update_pr_head(repo, pr):
            return decide("wait", non_mutable_head_reason(repo, pr))
        suffix = "; existing auto-merge request remains queued" if auto_merge_enabled else ""
        if current_head_approved and merge_state == "BEHIND":
            freshness_reason = "current-head OpenCode review approved"
        elif current_head_approved:
            freshness_reason = (
                "current-head OpenCode review approved; "
                f"base branch is {behind_by} commit(s) ahead even though GitHub mergeability is {merge_state}"
            )
        elif merge_state == "BEHIND":
            freshness_reason = "auto-merge already enabled"
        else:
            freshness_reason = (
                "auto-merge already enabled; "
                f"base branch is {behind_by} commit(s) ahead even though GitHub mergeability is {merge_state}"
            )
        return request_branch_update(freshness_reason, suffix=suffix)

    if should_restamp_for_last_push_approval(
        repo,
        pr,
        merge_state,
        current_head_approved=current_head_approved,
        auto_merge_enabled=auto_merge_enabled,
    ):
        block_reason = last_push_approval_block_reason()
        if head_already_restamped_for_last_push_approval(pr):
            return decide(
                "wait",
                f"{block_reason}; last-push approval head refresh already exists on the latest commit, "
                "so wait for current-head checks, OpenCode approval, Strix evidence, a non-pusher approval, "
                "or GitHub native auto-merge to clear the remaining rule blocker",
            )
        if not update_branches:
            return decide(
                "wait",
                f"{block_reason}; last-push approval head refresh disabled by scheduler inputs",
            )
        if not branch_update_allowed:
            return decide(
                "wait",
                f"branch update limit reached ({branch_update_limit} update/run); "
                "defer last-push approval head refresh to the next scheduler run",
            )
        new_head = restamp_pr_head_for_last_push_approval(repo, pr, dry_run=dry_run)
        notes = ()
        if new_head:
            notes = (f"last-push approval head refresh created same-tree head {short_sha(new_head)}",)
        return finish(
            Decision(
                number,
                "restamp_head",
                f"{block_reason}; last-push approval head refresh requested with {mutation_token_label()} "
                f"inside GitHub Actions as {mutation_actor_label()}",
                notes,
            )
        )

    opencode_state = opencode_progress_state(pr, stale_after_minutes=stale_opencode_minutes)
    if opencode_state == "running":
        return decide("wait", "OpenCode review is already in progress")

    if (
        os.environ.get("GITHUB_EVENT_NAME") == "workflow_run"
        and has_current_head_deterministic_fallback_approval(pr)
    ):
        return decide(
            "wait",
            "current-head deterministic fallback is not merge evidence; defer real-model retry to the next scheduler heartbeat",
        )

    if behind_by and trigger_reviews:
        if not update_branches:
            return decide("wait", "current head has no OpenCode approval; branch update disabled before review dispatch")
        if not can_update_pr_head(repo, pr):
            head_repo = (pr.get("headRepository") or {}).get("nameWithOwner") or "<unknown>"
            return decide(
                "wait",
                f"current head has no OpenCode approval; branch is outdated before review dispatch, "
                f"but head repo {head_repo} is not writable by the scheduler credential",
            )
        if merge_state == "BEHIND":
            freshness_reason = "current head has no OpenCode approval; branch is outdated before review dispatch"
        else:
            freshness_reason = (
                "current head has no OpenCode approval; "
                f"base branch is {behind_by} commit(s) ahead before review dispatch even though "
                f"GitHub mergeability is {merge_state}"
            )
        return request_branch_update(freshness_reason)

    if merge_state == "UNKNOWN":
        if pr.get("autoMergeRequest"):
            return finish(
                disable_auto_merge_decision(
                    repo,
                    pr,
                    dry_run=dry_run,
                    reason="mergeability is still being calculated and no branch freshness evidence is available; wait for GitHub mergeability evidence before re-enabling auto-merge",
                )
            )
        return decide("wait", "mergeability is still being calculated and no branch freshness evidence is available")

    if current_head_approved:
        if pr.get("autoMergeRequest"):
            return decide("wait", auto_merge_wait_reason(merge_state, pr))
        if not same_repository_head(repo, pr):
            return decide("wait", external_head_merge_reason(repo, pr))
        if not enable_auto_merge_flag:
            return decide("wait", "current head is approved; auto-merge disabled by scheduler inputs")
        if merge_mode == "disabled":
            return decide("wait", "current head is approved; merge mode disabled by scheduler inputs")
        if merge_mode in {"direct", "direct_or_auto"}:
            if merge_mode == "direct_or_auto":
                try:
                    merge_pr(repo, pr, dry_run=dry_run)
                except RuntimeError as exc:
                    if not direct_merge_can_fallback_to_auto_merge(exc):
                        raise
                    block_detail = direct_merge_block_detail(exc)
                    enable_auto_merge(repo, pr, dry_run=dry_run)
                    return decide(
                        "auto_merge",
                        "current head is approved; direct merge was blocked by branch policy, "
                        "so auto-merge was enabled with the same head guard evidence; "
                        f"GitHub mergeability is {merge_state}; GitHub reported: {block_detail}",
                    )
                return decide(
                    "merge",
                    f"current head is approved; direct merge requested with {mutation_token_label()} "
                    f"and --match-head-commit while GitHub mergeability is {merge_state}",
                )
            return decide(
                "wait",
                f"current head is approved; direct merge waits for CLEAN mergeability; GitHub mergeability is {merge_state}",
            )
        if merge_mode != "auto":
            return decide("wait", f"current head is approved; unsupported merge mode: {merge_mode}")
        enable_auto_merge(repo, pr, dry_run=dry_run)
        return decide("auto_merge", "current head is approved; auto-merge enabled")

    if opencode_state == "stale" and not trigger_reviews:
        return decide(
            "wait",
            f"OpenCode review exceeded {stale_opencode_minutes} minute retry threshold; review dispatch disabled",
        )
    if opencode_state == "stale":
        if not review_dispatch_allowed:
            return decide(
                "wait",
                f"OpenCode review exceeded {stale_opencode_minutes} minute retry threshold; review dispatch limit reached",
            )
        dispatch_result = dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
        if dispatch_result == "already_running":
            return decide(
                "wait",
                "OpenCode review exceeded the status-check retry threshold, but a same-head workflow run is already active",
            )
        return decide(
            "review_dispatch",
            f"OpenCode review exceeded {stale_opencode_minutes} minute retry threshold; same-head OpenCode re-dispatched",
        )

    if trigger_reviews:
        strix_state = strix_evidence_state(pr)
        if strix_state == "missing":
            if not review_dispatch_allowed:
                return decide(
                    "wait",
                    "current head has no completed Strix evidence; review dispatch limit reached",
                )
            wait_reason = repository_dispatch_wait_reason(repo, security_workflow)
            if wait_reason:
                return decide("wait", f"current head has no completed Strix evidence; {wait_reason}")
            dispatch_strix_evidence(repo, security_workflow, pr, dry_run=dry_run)
            return decide(
                "security_dispatch",
                "current head has no completed Strix evidence; same-head Strix dispatched",
            )
        if strix_state == "running":
            return decide("wait", "same-head Strix evidence is still running")
        # Legacy trusted-base Strix self-test sentinel while this scheduler rollout lands:
        # same-head Strix and OpenCode dispatched
        if not review_dispatch_allowed:
            return decide(
                "wait",
                "current head has completed Strix evidence; review dispatch limit reached",
            )
        wait_reason = repository_dispatch_wait_reason(repo, workflow)
        if wait_reason:
            return decide("wait", f"current head has completed Strix evidence; {wait_reason}")
        dispatch_result = dispatch_opencode_review(repo, workflow, pr, dry_run=dry_run)
        if dispatch_result == "already_running":
            return decide(
                "wait",
                "current head has completed Strix evidence; same-head OpenCode workflow run is already active",
            )
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


def markdown_code_span(value: object) -> str:
    """Escape a value for a compact Markdown inline code span."""
    escaped = str(value).replace("`", "\\`")
    return f"`{escaped}`"


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
    lines.extend(last_push_approval_restamp_summary(decisions))
    lines.extend(external_head_update_summary(decisions))
    lines.extend(external_head_merge_summary(decisions))
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


def parse_conflict_changed_files(reason: str) -> list[str]:
    """Extract changed-file conflict hints from scheduler guidance text."""
    prefix = "changed files to inspect first: "
    for segment in reason.split(";"):
        segment = segment.strip()
        if not segment.startswith(prefix):
            continue
        return [
            file_path
            for file_path in (part.strip() for part in segment[len(prefix) :].split("|"))
            if file_path and not file_path.startswith("+")
        ]
    return []


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
        changed_files = parse_conflict_changed_files(decision.reason)
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
        if changed_files:
            lines.extend(
                [
                    "",
                    "Changed files to inspect first:",
                    *(f"- {markdown_code_span(path)}" for path in changed_files),
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
    token_label = mutation_token_label()
    actor_label = mutation_actor_label()
    lines = [
        "",
        "### Branch update requests",
        "",
        f"Requested `update-branch` for PR {pr_list} with `{token_label}`, guarded by the observed `expected_head_sha`.",
        f"This is intentionally done inside GitHub Actions, not from a maintainer's local `gh` credential, so the mechanical update is attributable to `{actor_label}`.",
        "Existing native auto-merge requests stay queued; branch freshness should not be repaired by disabling auto-merge first.",
        "The scheduler refuses a non-dry-run `update-branch` outside GitHub Actions; dispatch the workflow instead of running the mutation locally.",
        "This branch-update API path needs `pull-requests: write`; it does not require the scheduler job to widen repository `contents` to write.",
        "When repository permissions allow the mutation, GitHub records the resulting branch update under the selected workflow credential.",
        "The updated head is not merge evidence by itself. Wait for the new head to receive OpenCode approval, Strix evidence, required checks, and unresolved-thread checks before merge or auto-merge.",
    ]
    followups = [(decision, note) for decision in updates for note in decision.notes if "update-branch" in note]
    if followups:
        lines.extend(["", "Follow-up evidence:"])
        lines.extend(f"- PR #{decision.pr}: {note}" for decision, note in followups)
    return lines


def parse_last_push_approval_restamp_reason(reason: str) -> bool:
    """Return whether a reason describes a last-push approval head refresh."""
    return "last-push approval head refresh" in reason


def last_push_approval_restamp_summary(decisions: list[Decision]) -> list[str]:
    """Return a summary section explaining last-push approval restamps."""
    restamps = [decision for decision in decisions if parse_last_push_approval_restamp_reason(decision.reason)]
    if not restamps:
        return []
    token_label = mutation_token_label()
    actor_label = mutation_actor_label()
    lines = [
        "",
        "### Last-push approval head refresh",
        "",
        "These PRs were already current-head approved and had native auto-merge queued, but GitHub still reported `BLOCKED` while `reviewDecision` was `APPROVED`.",
        "That combination is a strong signal that `require_last_push_approval` is still unsatisfied because the approving maintainer also pushed the current head.",
        f"The scheduler may create a same-tree child commit with `{token_label}` as `{actor_label}` and move the same-repository PR branch with a `force=false` Git ref update.",
        "The refreshed head is not merge evidence by itself. Wait for required checks, same-head Strix evidence, OpenCode approval, review-thread checks, and an approving review from a non-pusher before merge.",
    ]
    for decision in restamps:
        lines.extend(["", f"- PR #{decision.pr}: {decision.reason}"])
        for note in decision.notes:
            if "last-push approval head refresh" in note:
                lines.append(f"  - {note}")
    return lines


def parse_external_head_update_reason(reason: str) -> str | None:
    """Extract the external head repository from non-mutable update guidance."""
    match = re.search(r"head repo ([^\s]+) is external and not writable", reason)
    if not match:
        return None
    return match.group(1)


def parse_external_head_merge_reason(reason: str) -> str | None:
    """Extract the external head repository from merge-exclusion guidance."""
    match = re.search(r"head repo ([^\s]+) is external; fork or external PR heads are excluded", reason)
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


def external_head_merge_summary(decisions: list[Decision]) -> list[str]:
    """Return a GitHub Actions Summary section for fork/external PR heads excluded from merge."""
    external_waits = [
        (decision, parse_external_head_merge_reason(decision.reason))
        for decision in decisions
        if parse_external_head_merge_reason(decision.reason)
    ]
    if not external_waits:
        return []

    lines = [
        "",
        "### External head merge excluded",
        "",
        "These PRs remain reviewable, but the scheduler will not direct-merge or enable auto-merge for fork or external heads. A maintainer must make the final merge decision after the current head stays approved and all required evidence is green.",
    ]
    for decision, head_repo in external_waits:
        lines.extend(
            [
                "",
                f"- PR #{decision.pr}: `{head_repo}` is external; keep review evidence current, then merge manually if policy allows.",
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
    if "without `workflows` permission" in lower_summary or "without workflows permission" in lower_summary:
        summary = (
            f"{summary}; workflow-file PRs need a scheduler mutation credential with GitHub `workflows` permission. "
            "Configure `PR_REVIEW_MERGE_TOKEN` or expand the selected GitHub App permission, then rerun the scheduler; "
            "do not leave this as a review comment for the PR author."
        )
    if "auto-merge is disabled" in lower_summary or "auto merge is disabled" in lower_summary:
        summary = (
            f"{summary}; native auto-merge is disabled for this repository. "
            "Use `--merge-mode direct_or_auto` so the scheduler attempts a guarded direct merge before queueing native auto-merge, "
            "or enable repository auto-merge when branch policy requires GitHub's queued merge path."
        )
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
    assert split_repo("owner/name") == ("owner", "name")
    assert split_repo("owner/name/extra") == ("owner", "name/extra")
    try:
        split_repo("owner")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    try:
        split_repo("/name")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    try:
        split_repo("owner/")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
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
                        "messageHeadline": "feat: sample",
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
    assert decision.action == "merge"
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
    assert "merge conflict repair is required before auto-merge can be queued" in decision.reason
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
    assert decision.action == "update_branch"
    assert "branch is outdated before review dispatch" in decision.reason
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
    assert decision.action == "update_branch"
    assert "branch is outdated before review dispatch" in decision.reason
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
    sample["mergeStateStatus"] = "CLEAN"
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
    assert "merge conflict repair is required before auto-merge can be queued" in decision.reason
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
    assert "auto-merge is not queued until merge conflict repair is pushed" in decision.reason
    sample["reviews"]["nodes"][0]["commit"]["oid"] = "old"
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
    blocked_sample = {
        "number": 2,
        "headRefOid": "abc",
        "baseRefName": "main",
        "baseRefOid": "base",
        "headRefName": "feature",
        "mergeStateStatus": "BLOCKED",
        "restMergeableState": "BLOCKED",
        "compareStatus": "identical",
        "compareBehindBy": 0,
        "isDraft": False,
        "isCrossRepository": False,
        "maintainerCanModify": False,
        "headRepository": {"nameWithOwner": "owner/repo"},
        "reviewDecision": "APPROVED",
        "autoMergeRequest": {"enabledAt": "2026-01-01T00:02:00Z"},
        "commits": {
            "nodes": [
                {
                    "commit": {
                        "oid": "abc",
                        "committedDate": "2026-06-25T16:38:22Z",
                        "messageHeadline": "ci: exercise blocked approval path",
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
        "statusCheckRollup": {
            "contexts": {
                "nodes": [
                    {
                        "__typename": "CheckRun",
                        "name": "strix",
                        "status": "COMPLETED",
                        "conclusion": "SUCCESS",
                    }
                ]
            }
        },
    }
    decision = inspect_pr(
        "owner/repo",
        blocked_sample,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    assert decision.action == "restamp_head"
    assert "require_last_push_approval" in decision.reason
    assert "last-push approval head refresh requested" in decision.reason
    restamp_guidance = decision_guidance(decision)
    assert restamp_guidance
    assert restamp_guidance["type"] == "last_push_approval_restamp"
    assert restamp_guidance["head_guard"] == "live PR head check plus force=false Git ref update"
    blocked_sample["commits"]["nodes"][0]["commit"]["messageHeadline"] = LAST_PUSH_APPROVAL_RESTAMP_MESSAGE
    decision = inspect_pr(
        "owner/repo",
        blocked_sample,
        dry_run=True,
        trigger_reviews=True,
        enable_auto_merge_flag=True,
        update_branches=True,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    assert decision.action == "wait"
    assert "head refresh already exists" in decision.reason
    assert contract_decision(Decision(1, "update_branch", "ok")) == "UPDATE_BRANCH"
    assert contract_decision(Decision(1, "restamp_head", "ok")) == "UPDATE_BRANCH"
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
    restamp_guidance = decision_guidance(
        Decision(1, "restamp_head", f"{last_push_approval_block_reason()}; last-push approval head refresh requested")
    )
    assert restamp_guidance
    assert restamp_guidance["type"] == "last_push_approval_restamp"
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
        [Decision(1, "restamp_head", f"{last_push_approval_block_reason()}; last-push approval head refresh requested")],
        counts={"restamp_head": 1},
        dry_run=True,
        base_branch="main",
        project_flow="github-flow",
    )
    assert payload["decisions"][0]["contract_decision"] == "UPDATE_BRANCH"
    assert payload["decisions"][0]["guidance"]["type"] == "last_push_approval_restamp"
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
    parser.add_argument(
        "--review-dispatch-limit",
        type=int,
        default=int(os.environ.get("REVIEW_DISPATCH_LIMIT", "1")),
        help="Maximum OpenCode/Strix review dispatch actions per scheduler run; -1 means unlimited",
    )
    parser.add_argument(
        "--branch-update-limit",
        type=int,
        default=int(os.environ.get("BRANCH_UPDATE_LIMIT", "1")),
        help="Maximum update-branch mutations per scheduler run; -1 means unlimited",
    )
    parser.add_argument("--enable-auto-merge", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--merge-mode",
        choices=("auto", "direct", "direct_or_auto", "disabled"),
        default=os.environ.get("MERGE_MODE", "direct_or_auto"),
    )
    parser.add_argument("--update-branches", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--review-workflow", default="Required OpenCode Review")
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
    if args.review_dispatch_limit < -1:
        raise SystemExit("--review-dispatch-limit must be -1 or greater")
    if args.branch_update_limit < -1:
        raise SystemExit("--branch-update-limit must be -1 or greater")
    prs = fetch_pr(args.repo, args.pr_number) if args.pr_number else fetch_open_prs(args.repo, args.max_prs)
    decisions = []
    review_dispatches_used = 0
    branch_updates_used = 0
    for pr in prs:
        review_dispatch_allowed = (
            args.review_dispatch_limit < 0 or review_dispatches_used < args.review_dispatch_limit
        )
        branch_update_allowed = args.branch_update_limit < 0 or branch_updates_used < args.branch_update_limit
        try:
            decision = inspect_pr(
                args.repo,
                pr,
                dry_run=args.dry_run,
                trigger_reviews=args.trigger_reviews,
                review_dispatch_allowed=review_dispatch_allowed,
                branch_update_allowed=branch_update_allowed,
                branch_update_limit=args.branch_update_limit,
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
        if decision.action in {"review_dispatch", "security_dispatch"}:
            review_dispatches_used += 1
        if decision.action in {"update_branch", "restamp_head"}:
            branch_updates_used += 1
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
