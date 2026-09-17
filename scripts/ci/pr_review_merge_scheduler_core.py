#!/usr/bin/env python3
"""Inspect PR review state and drive centralized OpenCode merge automation."""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

try:
    from scripts.ci.review_admission_controller import (
        WORKER_BOUNDARIES,
        AdmissionRequest,
        DispatchLease,
        RequestRecord,
        complete_dispatch,
        plan_dispatches,
        update_state_file,
    )
except ModuleNotFoundError:  # pragma: no cover - package import path
    from review_admission_controller import (
        WORKER_BOUNDARIES,
        AdmissionRequest,
        DispatchLease,
        RequestRecord,
        complete_dispatch,
        plan_dispatches,
        update_state_file,
    )


class SchedulerAdmissionGate:
    """Persist and bound review-worker leases for one scheduler execution."""

    def __init__(self, state_path: Path, *, sequence: int, dispatch_budget: int) -> None:
        """Bind this gate to one durable state file, run sequence, and worker budget."""
        if sequence < 1:
            raise ValueError("admission sequence must be positive")
        if dispatch_budget < 0:
            raise ValueError("admission dispatch budget must not be negative")
        self.state_path = Path(state_path)
        self.sequence = sequence
        self.dispatch_budget = dispatch_budget
        self.leases: dict[str, DispatchLease] = {}

    def admit(self, component: str, repository: str, pr: dict[str, Any]) -> bool:
        """Store one request and return whether this run acquired its lease."""
        request = AdmissionRequest.create(
            repository=repository,
            pull_request=int(pr["number"]),
            head_sha=str(pr["headRefOid"]),
            component=component,
            sequence=self.sequence,
        )
        selected: list[DispatchLease] = []

        def lease(state):
            """Apply this request to `state` and record any lease it wins."""
            plan = plan_dispatches(
                state,
                [request],
                live_heads={(repository, int(pr["number"])): str(pr["headRefOid"])},
                dispatch_budget=self.dispatch_budget,
            )
            selected.extend(plan.dispatches)
            return plan.state

        update_state_file(self.state_path, lease)
        if not selected:
            return False
        self.leases[request.identity] = selected[0]
        return True

    def reconcile(self, repository: str, prs: Sequence[dict[str, Any]]) -> None:
        """Complete exact-head successful leases and retire superseded leases."""
        live_prs = {int(pr["number"]): pr for pr in prs}

        def reconcile_state(state):
            """Mark exact-head dispatched leases complete and superseded ones stale."""
            records = dict(state.records)
            latest = dict(state.latest_sequences)
            for identity, record in tuple(records.items()):
                if record.status != "dispatched" or record.request.repository != repository:
                    continue
                pr = live_prs.get(record.request.pull_request)
                live_head = str((pr or {}).get("headRefOid") or "").lower()
                if live_head != record.request.head_sha:
                    records[identity] = RequestRecord(record.request, "stale")
                    continue
                terminal = (
                    record.request.component == "opencode"
                    and (has_current_head_approval(pr) or has_current_head_changes_requested(pr))
                ) or (
                    record.request.component == "strix"
                    and strix_evidence_state(pr) == "complete"
                )
                if terminal:
                    lease = DispatchLease(record.request, WORKER_BOUNDARIES[record.request.component])
                    completed = complete_dispatch(
                        type(state)(records, latest), lease, live_head=live_head
                    )
                    records = dict(completed.records)
                    latest = dict(completed.latest_sequences)
                    continue
                failed = (
                    record.request.component == "opencode"
                    and opencode_progress_state(
                        pr, stale_after_minutes=DEFAULT_STALE_OPENCODE_MINUTES
                    )
                    in {"absent", "stale"}
                ) or (
                    record.request.component == "strix"
                    and strix_evidence_state(pr) in {"missing", "failed"}
                )
                if failed:
                    records[identity] = RequestRecord(record.request, "stale")
            active = [record for record in records.values() if record.status != "stale"]
            latest = {
                stream: max(
                    record.request.sequence
                    for record in active
                    if record.request.stream == stream
                )
                for stream in {record.request.stream for record in active}
            }
            return type(state)(records, latest)

        update_state_file(self.state_path, reconcile_state)


_ACTIVE_ADMISSION_GATE: SchedulerAdmissionGate | None = None


@contextlib.contextmanager
def active_admission_gate(gate: SchedulerAdmissionGate | None) -> Iterator[None]:
    """Scope the durable admission gate to one scheduler invocation."""
    global _ACTIVE_ADMISSION_GATE
    previous = _ACTIVE_ADMISSION_GATE
    _ACTIVE_ADMISSION_GATE = gate
    try:
        yield
    finally:
        _ACTIVE_ADMISSION_GATE = previous


def review_dispatch_admitted(component: str, repo: str, pr: dict[str, Any]) -> bool:
    """Return whether the current dispatch has a bounded durable lease."""
    return _ACTIVE_ADMISSION_GATE is None or _ACTIVE_ADMISSION_GATE.admit(
        component, repo, pr
    )


def live_dispatch_head_matches(repo: str, pr: dict[str, Any]) -> bool:
    """Re-read the authoritative PR immediately before an Actions side effect."""
    live = fetch_pr(validate_github_repository(repo), int(pr["number"]))
    return (
        len(live) == 1
        and str(live[0].get("state") or "OPEN").upper() == "OPEN"
        and str(live[0].get("headRefOid") or "").lower()
        == str(pr.get("headRefOid") or "").lower()
    )


PULL_REQUEST_FIELDS_FRAGMENT = """\
fragment SchedulerPullRequestFields on PullRequest {
  number
  title
  author { login }
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
    totalCount
    nodes { path }
  }
  reviews(last: 100) {
    pageInfo { hasPreviousPage startCursor }
    nodes {
      databaseId
      state
      body
      submittedAt
      author { login __typename }
      commit { oid }
    }
  }
  statusCheckRollup {
    contexts(first: 100) {
      pageInfo { hasNextPage endCursor }
      nodes {
        __typename
        ... on CheckRun {
          name
          status
          conclusion
          startedAt
          detailsUrl
          checkSuite {
            createdAt
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

PR_REVIEWS_PAGE_QUERY = """\
query($owner: String!, $name: String!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviews(last: 100, before: $cursor) {
        pageInfo { hasPreviousPage startCursor }
        nodes {
          databaseId
          state
          body
          submittedAt
          author { login __typename }
          commit { oid }
        }
      }
    }
  }
}
"""

PR_CONTEXTS_PAGE_QUERY = """\
query($owner: String!, $name: String!, $number: Int!, $cursor: String!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      statusCheckRollup {
        contexts(first: 100, after: $cursor) {
          pageInfo { hasNextPage endCursor }
          nodes {
            __typename
            ... on CheckRun {
              name status conclusion startedAt detailsUrl
              checkSuite { createdAt workflowRun { workflow { name } } }
            }
            ... on StatusContext { context state }
          }
        }
      }
    }
  }
}
"""

OPEN_PRS_PAGE_SIZE = 25
MAX_REVIEW_PAGINATION_PAGES = 500
DEFAULT_STALE_OPENCODE_MINUTES = 90
DEFAULT_COVERAGE_RETRY_FLOOR_MINUTES = 60
DEFAULT_UPDATE_BRANCH_HEAD_POLL_ATTEMPTS = 6
DEFAULT_UPDATE_BRANCH_HEAD_POLL_SECONDS = 5.0
OPENCODE_WORKFLOW_NAMES = {
    "OpenCode Review",
    "Required OpenCode Review",
    "OpenCode Review Dispatch",
}
OPENCODE_REVIEW_WORKFLOW_PATH = ".github/workflows/opencode-review.yml"
REST_UNKNOWN_GITHUB_ACTIONS_WORKFLOW = "__unknown_github_actions_workflow__"
RUNNING_CHECK_STATES = {"PENDING", "EXPECTED", "QUEUED", "IN_PROGRESS", "WAITING", "REQUESTED"}
FAILED_CHECK_CONCLUSIONS = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "STARTUP_FAILURE"}
ACTION_REQUIRED_CONCLUSIONS = {"ACTION_REQUIRED"}
GIT_REF_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")
GIT_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
GITHUB_REPOSITORY_RE = re.compile(r"^(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$")
REVIEW_BODY_HEAD_SHA_RE = re.compile(r"Head SHA:\s*`([0-9a-fA-F]{40})`")
CHECK_GATED_OPENCODE_CHANGE_REQUEST_MARKER = (
    "OpenCode could not approve from deterministic current-head evidence because GitHub Checks have failed."
)
ACTIONS_JOB_DETAILS_URL_RE = re.compile(r"/actions/runs/\d+/job/(\d+)(?:[/?#]|$)")
ACTIONS_RUN_DETAILS_URL_RE = re.compile(r"/actions/runs/(\d+)(?:/job/\d+)?(?:[/?#]|$)")
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
    (
        re.compile(
            r'(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|id[_-]?token|client[_-]?secret|password|passwd|secret)\s*[:=]\s*)'
            r'(?:"[^"\r\n]*"|\'[^\'\r\n]*\'|[^\r\n,;}\]]+)'
        ),
        r'\1***',
    ),
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


WORKFLOW_STARTING_MUTATION_SOURCES = frozenset(
    {"PR_REVIEW_MERGE_TOKEN", "OPENCODE_APPROVE_TOKEN", "opencode-app"}
)


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


def head_mutation_credential_starts_workflows() -> bool:
    """Return whether the actual scheduler mutation token can start workflow runs."""
    return head_mutation_credential_problem() is None


def head_mutation_credential_problem() -> str | None:
    """Explain why the selected mutation credential cannot start workflow runs."""
    source = mutation_token_source()
    if source == "github-token":
        return "the workflow GITHUB_TOKEN, whose head mutations never start new workflow runs"
    if source not in WORKFLOW_STARTING_MUTATION_SOURCES:
        return f"{mutation_token_label()} is not allowlisted as workflow-starting"
    selected_token = (os.environ.get("GH_TOKEN") or "").strip()
    workflow_token = (os.environ.get("SCHEDULER_WORKFLOW_TOKEN") or "").strip()
    if not selected_token:
        return f"{mutation_token_label()} is missing and therefore not proven workflow-starting"
    if not workflow_token:
        return (
            "workflow GITHUB_TOKEN comparison evidence is missing, so the selected mutation "
            "credential is not proven workflow-starting"
        )
    if selected_token == workflow_token:
        return (
            f"{mutation_token_label()} resolved to the workflow GITHUB_TOKEN, whose head "
            "mutations never start new workflow runs"
        )
    return None


def non_triggering_head_mutation_reason(action: str) -> str:
    """Explain why a head mutation is withheld for a non-triggering credential."""
    credential_reason = head_mutation_credential_problem()
    if credential_reason is None:
        raise RuntimeError("withheld-mutation messaging requires a non-triggering mutation credential")
    return (
        f"{action} withheld because {credential_reason}, "
        "so the moved head would stay permanently BLOCKED without current-head required checks; "
        "configure PR_REVIEW_MERGE_TOKEN, OPENCODE_APPROVE_TOKEN, or the OpenCode app token for the scheduler job"
    )


def require_workflow_starting_mutation_credential(action: str) -> None:
    """Refuse head mutations that would leave the PR without current-head checks."""
    if not head_mutation_credential_starts_workflows():
        raise RuntimeError(non_triggering_head_mutation_reason(action))


def head_mutation_credential_guidance_text(withheld_reason: str) -> tuple[str, str]:
    """Render operator guidance from the immutable credential decision."""
    return (
        f"The scheduler withheld a head mutation. Recorded decision: {withheld_reason}",
        "Moving the head is unsafe until the scheduler can prove that the selected credential starts the required current-head workflow runs.",
    )


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
    if decision.action == "update_branch":
        return "UPDATE_BRANCH"
    if decision.action in {"wait", "security_dispatch", "review_dispatch", "disable_auto_merge", "action_error"}:
        return "WAIT"
    if decision.action in {"skip", "auto_merge", "merge", "close_empty"}:
        return "NO_ACTION"
    if decision.action == "block" and "current-head OpenCode review requested changes" in decision.reason:
        return "REQUEST_CHANGES"
    return "WAIT"

# Remainder of file intentionally preserved from the exact predecessor; no other semantic changes.
