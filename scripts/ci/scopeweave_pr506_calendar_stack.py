"""Audit the ScopeWeave calendar stack after PR #506 actually merges."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

TARGET_REPOSITORY = "ContextualWisdomLab/scopeweave"
PREREQUISITE_PR = 506


class AuditError(RuntimeError):
    """Raised when live input cannot satisfy the bounded audit contract."""


def validate_trigger(payload: Mapping[str, Any]) -> None:
    """Require the exact closed-and-merged event for ScopeWeave PR #506."""
    repository = payload.get("repository")
    pull_request = payload.get("pull_request")
    valid = (
        payload.get("action") == "closed"
        and isinstance(repository, Mapping)
        and repository.get("full_name") == TARGET_REPOSITORY
        and isinstance(pull_request, Mapping)
        and pull_request.get("number") == PREREQUISITE_PR
        and pull_request.get("merged") is True
    )
    if not valid:
        raise AuditError("expected ScopeWeave PR #506 actual merged event")


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ANCESTRY_OK = frozenset({"ahead", "identical"})


@dataclass(frozen=True)
class RestackAssessment:
    """Describe the bounded reconciliation actions and review order."""

    first_action: str
    second_action: str
    review_ready_order: tuple[int, int] = (539, 541)


def prerequisite_resolved(
    prerequisite: Mapping[str, Any],
    develop: Mapping[str, Any],
    merge_to_develop_status: str,
) -> bool:
    """Return whether #506's live merge is present in protected develop."""
    merge_sha = prerequisite.get("merge_commit_sha")
    develop_sha = develop.get("sha")
    return bool(
        prerequisite.get("state") == "closed"
        and prerequisite.get("merged") is True
        and isinstance(merge_sha, str)
        and _SHA_RE.fullmatch(merge_sha)
        and develop.get("name") == "develop"
        and develop.get("protected") is True
        and isinstance(develop_sha, str)
        and _SHA_RE.fullmatch(develop_sha)
        and merge_to_develop_status in _ANCESTRY_OK
    )


def assess_restack(
    *,
    protected_branch: str,
    first_base_ref: str,
    develop_to_first_status: str,
    first_head_ref: str,
    second_base_ref: str,
    first_to_second_status: str,
) -> RestackAssessment:
    """Classify #539 and #541 reconciliation without mutating either branch."""
    first_contains_develop = develop_to_first_status in _ANCESTRY_OK
    if not first_contains_develop:
        first_action = "restack"
    elif first_base_ref != protected_branch:
        first_action = "retarget"
    else:
        first_action = "none"

    second_contains_first = first_to_second_status in _ANCESTRY_OK
    if second_base_ref != first_head_ref or not second_contains_first:
        second_action = "restack-now"
    elif first_action == "restack":
        second_action = "restack-after-539"
    else:
        second_action = "none"

    return RestackAssessment(
        first_action=first_action,
        second_action=second_action,
    )



@dataclass(frozen=True)
class CheckSummary:
    """Summarize latest exact-commit check evidence and required blockers."""

    required_states: dict[str, str] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()
    all_required_passing: bool = False


@dataclass(frozen=True)
class ReviewSummary:
    """Summarize formal reviews and unresolved inline review threads."""

    total_submissions: int
    current_approvals: tuple[str, ...]
    qualifying_independent_approvals: tuple[str, ...]
    current_changes_requested: tuple[str, ...]
    stale_reviewers: tuple[str, ...]
    unresolved_threads: int


def _record_id(record: Mapping[str, Any]) -> int:
    """Return a sortable numeric identifier for an API record."""
    value = record.get("id")
    return value if isinstance(value, int) else -1


def _check_run_state(run: Mapping[str, Any]) -> str:
    """Normalize one check-run state without promoting non-success conclusions."""
    if run.get("status") != "completed":
        return "pending"
    conclusion = run.get("conclusion")
    return conclusion if isinstance(conclusion, str) and conclusion else "unknown"


def summarize_checks(
    *,
    required_contexts: Sequence[str],
    check_runs: Sequence[Mapping[str, Any]],
    statuses: Sequence[Mapping[str, Any]],
) -> CheckSummary:
    """Deduplicate check evidence and require literal success for each context."""
    latest_runs: dict[str, Mapping[str, Any]] = {}
    for run in check_runs:
        name = run.get("name")
        if not isinstance(name, str) or not name:
            continue
        prior = latest_runs.get(name)
        if prior is None or _record_id(run) > _record_id(prior):
            latest_runs[name] = run

    latest_statuses: dict[str, Mapping[str, Any]] = {}
    for status in statuses:
        context = status.get("context")
        if not isinstance(context, str) or not context:
            continue
        prior = latest_statuses.get(context)
        if prior is None or _record_id(status) > _record_id(prior):
            latest_statuses[context] = status

    observed: dict[str, str] = {
        name: _check_run_state(run) for name, run in latest_runs.items()
    }
    for context, status in latest_statuses.items():
        if context not in observed:
            state = status.get("state")
            observed[context] = state if isinstance(state, str) and state else "unknown"

    required_states = {
        context: observed.get(context, "absent") for context in required_contexts
    }
    blockers = tuple(
        f"{context}:{state}"
        for context, state in required_states.items()
        if state != "success"
    )
    return CheckSummary(
        required_states=required_states,
        counts=dict(Counter(observed.values())),
        blockers=blockers,
        all_required_passing=not blockers,
    )


def _review_login(review: Mapping[str, Any]) -> str | None:
    """Return a reviewer's login when the review carries a valid user object."""
    user = review.get("user")
    if not isinstance(user, Mapping):
        return None
    login = user.get("login")
    return login if isinstance(login, str) and login else None


def _reviewer_is_bot(review: Mapping[str, Any], login: str) -> bool:
    """Detect bot reviewers using both GitHub type and conventional suffix."""
    user = review.get("user")
    user_type = user.get("type") if isinstance(user, Mapping) else None
    return user_type == "Bot" or login.endswith("[bot]")


def summarize_reviews(
    *,
    head_sha: str,
    author_login: str,
    reviews: Sequence[Mapping[str, Any]],
    threads: Sequence[Mapping[str, Any]],
) -> ReviewSummary:
    """Bind formal review states to the exact current head and count threads."""
    latest_by_reviewer: dict[str, Mapping[str, Any]] = {}
    for review in reviews:
        login = _review_login(review)
        if login is None:
            continue
        prior = latest_by_reviewer.get(login)
        if prior is None or _record_id(review) > _record_id(prior):
            latest_by_reviewer[login] = review

    current_approvals: list[str] = []
    qualifying: list[str] = []
    current_changes: list[str] = []
    stale: list[str] = []
    for login, review in latest_by_reviewer.items():
        state = review.get("state")
        current = review.get("commit_id") == head_sha
        if not current:
            stale.append(login)
            continue
        if state == "APPROVED":
            current_approvals.append(login)
            if login != author_login and not _reviewer_is_bot(review, login):
                qualifying.append(login)
        elif state == "CHANGES_REQUESTED":
            current_changes.append(login)

    unresolved = sum(1 for thread in threads if thread.get("isResolved") is not True)
    return ReviewSummary(
        total_submissions=len(reviews),
        current_approvals=tuple(sorted(current_approvals)),
        qualifying_independent_approvals=tuple(sorted(qualifying)),
        current_changes_requested=tuple(sorted(current_changes)),
        stale_reviewers=tuple(sorted(stale)),
        unresolved_threads=unresolved,
    )


@dataclass(frozen=True)
class DevelopState:
    """Represent the live protected integration branch and required contexts."""

    name: str
    sha: str
    protected: bool
    required_contexts: tuple[str, ...]


@dataclass(frozen=True)
class PullRequestState:
    """Represent one live pull request without trusting its body text."""

    number: int
    state: str
    merged: bool
    draft: bool
    base_ref: str
    base_sha: str
    head_ref: str
    head_sha: str
    merge_commit_sha: str | None
    author_login: str
    mergeable: bool | None
    mergeable_state: str


@dataclass(frozen=True)
class PullRequestAudit:
    """Combine live pull-request metadata with exact-head evidence."""

    pull_request: PullRequestState
    checks: CheckSummary
    reviews: ReviewSummary


@dataclass(frozen=True)
class StackAudit:
    """Capture the complete merge-triggered ScopeWeave stack observation."""

    develop: DevelopState
    prerequisite: PullRequestState
    prerequisite_resolved: bool
    merge_to_develop_status: str
    first: PullRequestAudit
    second: PullRequestAudit
    prerequisite_to_first_status: str
    develop_to_first_status: str
    first_to_second_status: str
    restack: RestackAssessment


def managed_marker(target_pr: int) -> str:
    """Return the stable marker for one managed calendar-stack comment."""
    if target_pr not in (539, 541):
        raise AuditError("managed comment target must be #539 or #541")
    return f"<!-- scopeweave-pr506-calendar-stack:v1 target={target_pr} -->"


def select_managed_comment(
    comments: Sequence[Mapping[str, Any]], target_pr: int
) -> int | None:
    """Select one exact bot-owned marker comment and fail on ambiguity."""
    marker = managed_marker(target_pr)
    matches: list[int] = []
    for comment in comments:
        user = comment.get("user")
        body = comment.get("body")
        comment_id = comment.get("id")
        if (
            isinstance(user, Mapping)
            and user.get("login") == "github-actions[bot]"
            and isinstance(body, str)
            and body.startswith(marker)
            and isinstance(comment_id, int)
        ):
            matches.append(comment_id)
    if len(matches) > 1:
        raise AuditError(f"duplicate managed comments for #{target_pr}")
    return matches[0] if matches else None


def _short_sha(sha: str | None) -> str:
    """Render a validated-looking SHA compactly for operator-facing output."""
    return sha[:12] if isinstance(sha, str) else "none"


def _yes_no(value: bool) -> str:
    """Render a boolean as an unambiguous operator-facing word."""
    return "yes" if value else "no"


def _format_names(values: Sequence[str]) -> str:
    """Render a bounded login sequence or an explicit none marker."""
    return ", ".join(f"`{value}`" for value in values) if values else "none"


def _format_checks(summary: CheckSummary) -> str:
    """Render required check states in their live branch-protection order."""
    if not summary.required_states:
        return "- required contexts: none declared"
    lines = [
        f"  - `{context}`: `{state}`"
        for context, state in summary.required_states.items()
    ]
    blockers = ", ".join(f"`{item}`" for item in summary.blockers) or "none"
    return "\n".join(["- required contexts:", *lines, f"- blockers: {blockers}"])


def _format_pr_section(label: str, audit: PullRequestAudit) -> str:
    """Render one calendar PR's exact metadata, checks, and review evidence."""
    pr = audit.pull_request
    reviews = audit.reviews
    return "\n".join(
        [
            f"### {label}",
            (
                f"- #{pr.number} `{pr.head_ref}@{_short_sha(pr.head_sha)}` → "
                f"`{pr.base_ref}@{_short_sha(pr.base_sha)}`"
            ),
            (
                f"- state: `{pr.state}` · Draft: **{_yes_no(pr.draft)}** · "
                f"mergeable: `{pr.mergeable}` / `{pr.mergeable_state}`"
            ),
            _format_checks(audit.checks),
            (
                f"- reviews: formal submissions {reviews.total_submissions}; "
                f"current-head approvals {_format_names(reviews.current_approvals)}; "
                "qualifying independent approvals "
                f"{_format_names(reviews.qualifying_independent_approvals)}; "
                "current-head changes requested "
                f"{_format_names(reviews.current_changes_requested)}; "
                f"stale reviewers {_format_names(reviews.stale_reviewers)}; "
                f"unresolved threads {reviews.unresolved_threads}"
            ),
        ]
    )


def _first_action_text(action: str) -> str:
    """Translate the #539 restack classification into an imperative."""
    return {
        "restack": "reconcile its bounded diff onto live protected `develop`, then retarget",
        "retarget": "retarget its base to live protected `develop`; no source rewrite is indicated",
        "none": "retain its current head/base; no restack is indicated",
    }[action]


def _second_action_text(action: str) -> str:
    """Translate the #541 restack classification into an imperative."""
    return {
        "restack-after-539": "wait for #539's reconciled exact head, then restack onto that head",
        "restack-now": "reconcile onto #539's exact current head before review",
        "none": "retain the current child stack; re-check only if #539 moves",
    }[action]


def render_report(audit: StackAudit, *, target_pr: int) -> str:
    """Render one idempotent combined report for #539 or #541."""
    marker = managed_marker(target_pr)
    prerequisite_word = "resolved" if audit.prerequisite_resolved else "not resolved"
    report = "\n".join(
        [
            marker,
            "## #506 merge-triggered calendar-subscription stack audit",
            "",
            (
                f"Observed protected `{audit.develop.name}@"
                f"{_short_sha(audit.develop.sha)}` (protected: "
                f"**{_yes_no(audit.develop.protected)}**)."
            ),
            (
                f"#506 prerequisite: **{prerequisite_word}** · live state "
                f"`{audit.prerequisite.state}` / merged `{audit.prerequisite.merged}` · "
                f"merge→develop ancestry `{audit.merge_to_develop_status}`."
            ),
            (
                "Live ancestry: #506 head→#539 "
                f"`{audit.prerequisite_to_first_status}` · develop→#539 "
                f"`{audit.develop_to_first_status}` · #539→#541 "
                f"`{audit.first_to_second_status}`."
            ),
            "",
            _format_pr_section("Calendar domain", audit.first),
            "",
            _format_pr_section("Calendar SQLite persistence", audit.second),
            "",
            "## Restack and next review-ready order",
            (
                f"1. **#539 first** — {_first_action_text(audit.restack.first_action)}; "
                "rerun exact-head required checks, keep unresolved findings at zero, "
                "then remove Draft and request an independent current-head review."
            ),
            (
                f"2. **#541 second** — {_second_action_text(audit.restack.second_action)}; "
                "rerun exact-head required checks after the parent head is stable, "
                "then remove Draft and request an independent current-head review."
            ),
            "",
            (
                "No source branch, Draft flag, base, review, or merge state was mutated "
                "by this read-mostly audit; only this bot-owned marker comment is managed."
            ),
        ]
    )
    if len(report) > 60_000:
        raise AuditError("rendered audit report exceeds the bounded comment size")
    return report

REPOSITORY_API_ROOT = "/repos/ContextualWisdomLab/scopeweave"
_COMPARE_STATES = frozenset({"ahead", "behind", "diverged", "identical"})


def _nested_mapping(value: Any) -> Mapping[str, Any] | None:
    """Return a nested mapping while keeping untrusted JSON explicit."""
    return value if isinstance(value, Mapping) else None


def _valid_ref(value: Any) -> bool:
    """Return whether an API ref is a bounded non-empty string."""
    return isinstance(value, str) and 0 < len(value) <= 255 and "\x00" not in value


def parse_pull_request(
    payload: Mapping[str, Any], *, expected_number: int
) -> PullRequestState:
    """Validate one same-repository pull-request API object."""
    base = _nested_mapping(payload.get("base"))
    head = _nested_mapping(payload.get("head"))
    user = _nested_mapping(payload.get("user"))
    base_repo = _nested_mapping(base.get("repo")) if base else None
    head_repo = _nested_mapping(head.get("repo")) if head else None
    if (
        base_repo is None
        or head_repo is None
        or base_repo.get("full_name") != TARGET_REPOSITORY
        or head_repo.get("full_name") != TARGET_REPOSITORY
    ):
        raise AuditError("pull request must preserve a same-repository stack")

    base_ref = base.get("ref") if base else None
    base_sha = base.get("sha") if base else None
    head_ref = head.get("ref") if head else None
    head_sha = head.get("sha") if head else None
    merge_commit_sha = payload.get("merge_commit_sha")
    mergeable = payload.get("mergeable")
    valid = (
        payload.get("number") == expected_number
        and isinstance(payload.get("state"), str)
        and isinstance(payload.get("merged"), bool)
        and isinstance(payload.get("draft"), bool)
        and _valid_ref(base_ref)
        and isinstance(base_sha, str)
        and _SHA_RE.fullmatch(base_sha)
        and _valid_ref(head_ref)
        and isinstance(head_sha, str)
        and _SHA_RE.fullmatch(head_sha)
        and (
            merge_commit_sha is None
            or (
                isinstance(merge_commit_sha, str)
                and _SHA_RE.fullmatch(merge_commit_sha)
            )
        )
        and user is not None
        and isinstance(user.get("login"), str)
        and user.get("login")
        and (mergeable is None or isinstance(mergeable, bool))
        and isinstance(payload.get("mergeable_state"), str)
    )
    if not valid:
        raise AuditError(f"invalid pull request API shape for #{expected_number}")

    return PullRequestState(
        number=expected_number,
        state=str(payload["state"]),
        merged=bool(payload["merged"]),
        draft=bool(payload["draft"]),
        base_ref=str(base_ref),
        base_sha=str(base_sha),
        head_ref=str(head_ref),
        head_sha=str(head_sha),
        merge_commit_sha=(str(merge_commit_sha) if merge_commit_sha else None),
        author_login=str(user["login"]),
        mergeable=mergeable,
        mergeable_state=str(payload["mergeable_state"]),
    )


def parse_develop(payload: Mapping[str, Any]) -> DevelopState:
    """Validate the exact protected develop branch and required contexts."""
    commit = _nested_mapping(payload.get("commit"))
    sha = commit.get("sha") if commit else None
    if (
        payload.get("name") != "develop"
        or payload.get("protected") is not True
        or not isinstance(sha, str)
        or not _SHA_RE.fullmatch(sha)
    ):
        raise AuditError("expected live protected develop branch metadata")

    contexts: tuple[str, ...] = ()
    protection = _nested_mapping(payload.get("protection"))
    required = (
        _nested_mapping(protection.get("required_status_checks"))
        if protection
        else None
    )
    raw_contexts = required.get("contexts") if required else None
    if isinstance(raw_contexts, list):
        contexts = tuple(
            context
            for context in raw_contexts
            if isinstance(context, str) and context
        )
    return DevelopState(
        name="develop",
        sha=sha,
        protected=True,
        required_contexts=contexts,
    )


def comparison_status(payload: Any) -> str:
    """Validate one GitHub compare status used for ancestry decisions."""
    if not isinstance(payload, Mapping) or payload.get("status") not in _COMPARE_STATES:
        raise AuditError("invalid GitHub comparison status")
    return str(payload["status"])


def _collect_pull_request_audit(
    api: Any,
    pull_request: PullRequestState,
    required_contexts: Sequence[str],
) -> PullRequestAudit:
    """Collect exact-head checks, formal reviews, and all review threads."""
    head_sha = pull_request.head_sha
    check_runs = api.get_paginated_list(
        f"{REPOSITORY_API_ROOT}/commits/{head_sha}/check-runs",
        key="check_runs",
    )
    statuses = api.get_paginated_list(
        f"{REPOSITORY_API_ROOT}/commits/{head_sha}/status",
        key="statuses",
    )
    reviews = api.get_paginated_list(
        f"{REPOSITORY_API_ROOT}/pulls/{pull_request.number}/reviews"
    )
    threads = api.review_threads(pull_request.number)
    return PullRequestAudit(
        pull_request=pull_request,
        checks=summarize_checks(
            required_contexts=required_contexts,
            check_runs=check_runs,
            statuses=statuses,
        ),
        reviews=summarize_reviews(
            head_sha=head_sha,
            author_login=pull_request.author_login,
            reviews=reviews,
            threads=threads,
        ),
    )


def collect_stack_audit(api: Any, event: Mapping[str, Any]) -> StackAudit:
    """Re-fetch all live state and produce a deterministic stack audit."""
    validate_trigger(event)
    prerequisite = parse_pull_request(
        api.get(f"{REPOSITORY_API_ROOT}/pulls/506"), expected_number=506
    )
    if (
        prerequisite.state != "closed"
        or prerequisite.merged is not True
        or prerequisite.merge_commit_sha is None
    ):
        raise AuditError("live #506 is not merged; refusing stale event authority")

    develop = parse_develop(api.get(f"{REPOSITORY_API_ROOT}/branches/develop"))
    first_pr = parse_pull_request(
        api.get(f"{REPOSITORY_API_ROOT}/pulls/539"), expected_number=539
    )
    second_pr = parse_pull_request(
        api.get(f"{REPOSITORY_API_ROOT}/pulls/541"), expected_number=541
    )

    merge_to_develop = comparison_status(
        api.get(
            f"{REPOSITORY_API_ROOT}/compare/"
            f"{prerequisite.merge_commit_sha}...{develop.sha}"
        )
    )
    prerequisite_to_first = comparison_status(
        api.get(
            f"{REPOSITORY_API_ROOT}/compare/"
            f"{prerequisite.head_sha}...{first_pr.head_sha}"
        )
    )
    develop_to_first = comparison_status(
        api.get(
            f"{REPOSITORY_API_ROOT}/compare/{develop.sha}...{first_pr.head_sha}"
        )
    )
    first_to_second = comparison_status(
        api.get(
            f"{REPOSITORY_API_ROOT}/compare/{first_pr.head_sha}...{second_pr.head_sha}"
        )
    )

    restack = assess_restack(
        protected_branch=develop.name,
        first_base_ref=first_pr.base_ref,
        develop_to_first_status=develop_to_first,
        first_head_ref=first_pr.head_ref,
        second_base_ref=second_pr.base_ref,
        first_to_second_status=first_to_second,
    )
    return StackAudit(
        develop=develop,
        prerequisite=prerequisite,
        prerequisite_resolved=prerequisite_resolved(
            {
                "state": prerequisite.state,
                "merged": prerequisite.merged,
                "merge_commit_sha": prerequisite.merge_commit_sha,
            },
            {
                "name": develop.name,
                "protected": develop.protected,
                "sha": develop.sha,
            },
            merge_to_develop,
        ),
        merge_to_develop_status=merge_to_develop,
        first=_collect_pull_request_audit(
            api, first_pr, develop.required_contexts
        ),
        second=_collect_pull_request_audit(
            api, second_pr, develop.required_contexts
        ),
        prerequisite_to_first_status=prerequisite_to_first,
        develop_to_first_status=develop_to_first,
        first_to_second_status=first_to_second,
        restack=restack,
    )


def upsert_report(api: Any, target_pr: int, body: str) -> str:
    """Create, update, or preserve one exact bot-owned marker comment."""
    marker = managed_marker(target_pr)
    if not body.startswith(marker):
        raise AuditError("managed report body is missing its exact marker")
    comments = api.get_paginated_list(
        f"{REPOSITORY_API_ROOT}/issues/{target_pr}/comments"
    )
    comment_id = select_managed_comment(comments, target_pr)
    if comment_id is None:
        api.post(
            f"{REPOSITORY_API_ROOT}/issues/{target_pr}/comments", {"body": body}
        )
        return "created"
    existing = next(
        comment
        for comment in comments
        if comment.get("id") == comment_id
    )
    if existing.get("body") == body:
        return "unchanged"
    api.patch(
        f"{REPOSITORY_API_ROOT}/issues/comments/{comment_id}", {"body": body}
    )
    return "updated"


def execute(
    api: Any,
    event: Mapping[str, Any],
    *,
    summary_path: Any = None,
) -> dict[int, str]:
    """Run the bounded audit, publish both comments, and write a step summary."""
    audit = collect_stack_audit(api, event)
    reports = {
        target: render_report(audit, target_pr=target) for target in (539, 541)
    }
    results = {
        target: upsert_report(api, target, reports[target]) for target in (539, 541)
    }
    if summary_path is not None:
        summary_body = reports[539].split("\n", 1)[1]
        with open(summary_path, "a", encoding="utf-8") as summary_file:
            summary_file.write(summary_body)
            summary_file.write("\n")
    return results

_GITHUB_API_URL = "https://api.github.com"
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_EVENT_BYTES = 1024 * 1024
_MAX_PAGES = 100
_REVIEW_THREADS_QUERY = """
query ScopeWeaveCalendarReviewThreads(
  $owner: String!
  $name: String!
  $number: Int!
  $cursor: String
) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        nodes {
          id
          isResolved
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
  }
}
"""


class GitHubApi:
    """Bounded GitHub REST/GraphQL client for the fixed ScopeWeave audit."""

    def __init__(self, token: str, *, opener: Any = None, timeout: int = 20) -> None:
        """Bind one bearer token, HTTPS opener, and bounded request timeout."""
        if not isinstance(token, str) or not token.strip():
            raise AuditError("GITHUB_TOKEN is required")
        if not isinstance(timeout, int) or timeout <= 0 or timeout > 120:
            raise AuditError("GitHub API timeout must be between 1 and 120 seconds")
        self._token = token
        self._opener = opener or urlopen
        self._timeout = timeout

    @staticmethod
    def _validate_path(path: str) -> None:
        """Allow only the fixed ScopeWeave repository namespace or GraphQL."""
        if not isinstance(path, str) or not path or len(path) > 2_048:
            raise AuditError("disallowed GitHub API path")
        parsed = urlsplit(path)
        allowed_repository_path = (
            parsed.path == REPOSITORY_API_ROOT
            or parsed.path.startswith(f"{REPOSITORY_API_ROOT}/")
        )
        if (
            parsed.scheme
            or parsed.netloc
            or parsed.fragment
            or parsed.path != path.split("?", 1)[0]
            or any(ord(character) < 32 for character in path)
            or not (allowed_repository_path or parsed.path == "/graphql")
        ):
            raise AuditError("disallowed GitHub API path")

    def _request(
        self,
        method: str,
        path: str,
        payload: Mapping[str, Any] | None = None,
    ) -> Any:
        """Issue one bounded JSON request and return decoded untrusted JSON."""
        self._validate_path(path)
        if method not in {"GET", "POST", "PATCH"}:
            raise AuditError("disallowed GitHub API method")
        data = None
        if payload is not None:
            if method == "GET":
                raise AuditError("GET requests cannot carry a JSON payload")
            data = json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(data) > 256 * 1024:
                raise AuditError("GitHub API request payload exceeds the bound")
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "User-Agent": "ContextualWisdomLab-scopeweave-pr506-audit/1",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{_GITHUB_API_URL}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self._opener(request, timeout=self._timeout) as response:
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise AuditError(f"GitHub API HTTP failure ({exc.code})") from exc
        except URLError as exc:
            raise AuditError("GitHub API transport failure") from exc
        except TimeoutError as exc:
            raise AuditError("GitHub API request timed out") from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise AuditError("GitHub API response exceeds the bound")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditError("GitHub API returned invalid JSON") from exc

    def get(self, path: str) -> Any:
        """Fetch one fixed-path GitHub API JSON object."""
        return self._request("GET", path)

    def post(self, path: str, payload: Mapping[str, Any]) -> Any:
        """Create one bounded GitHub resource under the fixed namespace."""
        return self._request("POST", path, payload)

    def patch(self, path: str, payload: Mapping[str, Any]) -> Any:
        """Update one bounded GitHub resource under the fixed namespace."""
        return self._request("PATCH", path, payload)

    def get_paginated_list(self, path: str, *, key: str | None = None) -> list[Any]:
        """Read every bounded REST page from either a list or keyed-list response."""
        self._validate_path(path)
        collected: list[Any] = []
        for page in range(1, _MAX_PAGES + 1):
            separator = "&" if "?" in path else "?"
            page_path = f"{path}{separator}{urlencode({'per_page': 100, 'page': page})}"
            payload = self.get(page_path)
            if key is None:
                items = payload
            elif isinstance(payload, Mapping):
                items = payload.get(key)
            else:
                items = None
            if not isinstance(items, list):
                raise AuditError("GitHub paginated response has an invalid list shape")
            collected.extend(items)
            if len(items) < 100:
                return collected
        raise AuditError("GitHub pagination exceeded the bounded page count")

    def review_threads(self, pr_number: int) -> list[Mapping[str, Any]]:
        """Read all inline review-thread resolution states through GraphQL."""
        if pr_number not in (539, 541):
            raise AuditError("review-thread target must be #539 or #541")
        cursor: str | None = None
        collected: list[Mapping[str, Any]] = []
        for _page in range(_MAX_PAGES):
            payload = self.post(
                "/graphql",
                {
                    "query": _REVIEW_THREADS_QUERY,
                    "variables": {
                        "owner": "ContextualWisdomLab",
                        "name": "scopeweave",
                        "number": pr_number,
                        "cursor": cursor,
                    },
                },
            )
            if not isinstance(payload, Mapping) or payload.get("errors"):
                raise AuditError("GitHub GraphQL review-thread query failed")
            data = _nested_mapping(payload.get("data"))
            repository = _nested_mapping(data.get("repository")) if data else None
            pull_request = (
                _nested_mapping(repository.get("pullRequest")) if repository else None
            )
            threads = (
                _nested_mapping(pull_request.get("reviewThreads"))
                if pull_request
                else None
            )
            nodes = threads.get("nodes") if threads else None
            page_info = (
                _nested_mapping(threads.get("pageInfo")) if threads else None
            )
            if not isinstance(nodes, list) or page_info is None:
                raise AuditError("GitHub GraphQL review-thread response is invalid")
            for node in nodes:
                if not isinstance(node, Mapping):
                    raise AuditError("GitHub GraphQL review thread is invalid")
                collected.append(node)
            has_next = page_info.get("hasNextPage")
            end_cursor = page_info.get("endCursor")
            if has_next is not True:
                return collected
            if not isinstance(end_cursor, str) or not end_cursor:
                raise AuditError("GitHub GraphQL pagination cursor is invalid")
            cursor = end_cursor
        raise AuditError("GitHub GraphQL pagination exceeded the bounded page count")


def _load_event(path: str) -> Mapping[str, Any]:
    """Read one bounded GitHub event JSON object from the runner filesystem."""
    try:
        with open(path, "rb") as event_file:
            raw = event_file.read(_MAX_EVENT_BYTES + 1)
    except OSError as exc:
        raise AuditError("unable to read GitHub event file") from exc
    if len(raw) > _MAX_EVENT_BYTES:
        raise AuditError("GitHub event file exceeds the bound")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditError("GitHub event file contains invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise AuditError("GitHub event payload must be a JSON object")
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    """Run the exact merge-event audit as a GitHub Actions command-line entrypoint."""
    parser = argparse.ArgumentParser(
        description="Audit ScopeWeave #539/#541 only after PR #506 actually merges."
    )
    parser.add_argument("--event-path", required=True)
    args = parser.parse_args(argv)
    try:
        token = os.environ.get("GITHUB_TOKEN", "")
        if not token:
            raise AuditError("GITHUB_TOKEN is required")
        event = _load_event(args.event_path)
        api = GitHubApi(token)
        results = execute(
            api,
            event,
            summary_path=os.environ.get("GITHUB_STEP_SUMMARY") or None,
        )
        print(json.dumps(results, sort_keys=True))
        return 0
    except AuditError as exc:
        print(f"scopeweave-pr506-calendar-stack: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

