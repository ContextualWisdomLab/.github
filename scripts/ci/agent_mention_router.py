#!/usr/bin/env python3
"""Route trusted pull-request comment mentions to CWL review agents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Sequence

CENTRAL_AUTOMATION_REPOSITORY = "ContextualWisdomLab/.github"
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
MENTION_PATTERNS = {
    "cwl-noema-review": re.compile(
        r"(?<![A-Za-z0-9_-])@cwl-noema-review(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    ),
    "opencode-agent": re.compile(
        r"(?<![A-Za-z0-9_-])@opencode-agent(?![A-Za-z0-9_-])",
        re.IGNORECASE,
    ),
}
AGENT_WORKFLOW_RUN_ENDPOINTS = {
    "cwl-noema-review": (
        f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/actions/workflows/"
        "noema-review.yml/runs"
    ),
    "opencode-agent": (
        f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/actions/workflows/"
        "pr-review-merge-scheduler.yml/runs"
    ),
}
REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
HEAD_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
BASE_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")
RECEIPT_RE = re.compile(r"<!-- cwl-agent-mention-receipt:(\d+) -->")
MAX_WORKFLOW_RUN_RECORDS = 10_000


@dataclass(frozen=True)
class MentionRequest:
    """Validated agent-mention request extracted from one issue comment event."""

    repository: str
    pull_request_number: int
    pull_request_head_sha: str
    pull_request_base_branch: str
    comment_id: int
    actor: str
    agents: tuple[str, ...]


class GitHubClient:
    """Small token-bound wrapper around ``gh api`` for JSON requests."""

    def __init__(self, token: str) -> None:
        """Initialize a client with one non-empty GitHub credential."""

        if not token:
            raise ValueError("GitHub token is required")
        self._token = token

    def request(
        self,
        args: Sequence[str],
        *,
        input_payload: dict[str, Any] | None = None,
    ) -> Any:
        """Execute ``gh api`` and decode its optional JSON response."""

        command = ["gh", "api", *args]
        if input_payload is not None:
            command.extend(["--input", "-"])
        environment = os.environ.copy()
        environment["GH_TOKEN"] = self._token
        completed = subprocess.run(
            command,
            input=None if input_payload is None else json.dumps(input_payload),
            text=True,
            capture_output=True,
            check=True,
            env=environment,
        )
        output = completed.stdout.strip()
        return None if not output else json.loads(output)


def exact_mentions(body: str) -> tuple[str, ...]:
    """Return supported exact agent mentions in deterministic order."""

    return tuple(
        name for name, pattern in MENTION_PATTERNS.items() if pattern.search(body)
    )


def receipt_marker(comment_id: int) -> str:
    """Return the hidden target-comment acknowledgement marker."""

    if comment_id < 1:
        raise ValueError("comment id must be positive")
    return f"<!-- cwl-agent-mention-receipt:{comment_id} -->"


def processed_comment_ids(comments: Sequence[dict[str, Any]]) -> frozenset[int]:
    """Extract local receipts authored by the trusted GitHub Actions bot only.

    These target-repository comments are a local optimization and user-facing
    acknowledgement. Central exact-key workflow-run records remain authoritative
    for cross-repository dispatch idempotency because PAT and installation-token
    identities can rotate and target-repository actors can be spoofed.
    """

    processed: set[int] = set()
    for comment in comments:
        user = comment.get("user") or {}
        if (
            str(user.get("login") or "").casefold()
            != "github-actions[bot]"
            or str(user.get("type") or "").casefold() != "bot"
        ):
            continue
        body = str(comment.get("body") or "")
        processed.update(int(match) for match in RECEIPT_RE.findall(body))
    return frozenset(processed)


def parse_event(event: dict[str, Any]) -> MentionRequest | None:
    """Return a validated mention request, or ``None`` for an ignored event."""

    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    repository = event.get("repository") or {}
    pull_request = event.get("pull_request") or {}
    if not issue.get("pull_request"):
        return None
    if pull_request.get("state") != "open":
        return None
    if str(comment.get("user", {}).get("type", "")).casefold() == "bot":
        return None
    if str(comment.get("author_association", "")).upper() not in TRUSTED_ASSOCIATIONS:
        return None
    agents = exact_mentions(str(comment.get("body") or ""))
    if not agents:
        return None

    repository_name = str(repository.get("full_name") or "").strip()
    actor = str(comment.get("user", {}).get("login") or "").strip()
    head_sha = str(pull_request.get("head", {}).get("sha") or "").strip()
    base_branch = str(pull_request.get("base", {}).get("ref") or "").strip()
    number = issue.get("number")
    comment_id = comment.get("id")
    if not REPOSITORY_RE.fullmatch(repository_name):
        raise ValueError(
            "agent mentions are limited to ContextualWisdomLab repositories"
        )
    if not isinstance(number, int) or number < 1:
        raise ValueError("pull request number is missing or invalid")
    if not isinstance(comment_id, int) or comment_id < 1:
        raise ValueError("comment id is missing or invalid")
    if comment_id in processed_comment_ids(event.get("conversation_comments") or ()):
        return None
    if not HEAD_SHA_RE.fullmatch(head_sha):
        raise ValueError("pull request head SHA is missing or invalid")
    if not BASE_BRANCH_RE.fullmatch(base_branch):
        raise ValueError("pull request base branch is missing or invalid")
    if not actor:
        raise ValueError("comment actor is missing")
    return MentionRequest(
        repository_name,
        number,
        head_sha.lower(),
        base_branch,
        comment_id,
        actor,
        agents,
    )


def parse_repository_allowlist(raw_value: str) -> frozenset[str]:
    """Parse and validate a comma-separated exact repository allowlist."""

    repositories = frozenset(
        part.strip() for part in raw_value.split(",") if part.strip()
    )
    invalid = sorted(
        repository
        for repository in repositories
        if not REPOSITORY_RE.fullmatch(repository)
    )
    if invalid:
        raise ValueError(f"invalid repository allowlist entries: {', '.join(invalid)}")
    return repositories


def eligible_agents(
    request: MentionRequest,
    *,
    opencode_allowlist: frozenset[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Partition requested agents into dispatchable and rejected handles."""

    dispatchable: list[str] = []
    rejected: list[str] = []
    if "cwl-noema-review" in request.agents:
        dispatchable.append("cwl-noema-review")
    if "opencode-agent" in request.agents:
        if request.repository in opencode_allowlist:
            dispatchable.append("opencode-agent")
        else:
            rejected.append("opencode-agent")
    return tuple(dispatchable), tuple(rejected)


def agent_invocation_key(request: MentionRequest, agent: str) -> str:
    """Return a deterministic opaque key for one exact agent invocation.

    The key binds repository, pull request, exact head, base branch, requested
    agent, source comment, and requesting actor. It contains no credential or
    provider response and is safe to place in workflow run names.
    """

    if agent not in AGENT_WORKFLOW_RUN_ENDPOINTS:
        raise ValueError(f"unsupported agent: {agent}")
    canonical = json.dumps(
        {
            "actor": request.actor,
            "agent": agent,
            "base_branch": request.pull_request_base_branch,
            "comment_id": request.comment_id,
            "head_sha": request.pull_request_head_sha,
            "pr_number": request.pull_request_number,
            "repository": request.repository,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def agent_invocation_marker(request: MentionRequest, agent: str) -> str:
    """Return the exact workflow-run marker for one agent invocation."""

    return f"[cwl-agent-invocation:{agent_invocation_key(request, agent)}]"


def _workflow_run_records(value: Any) -> tuple[dict[str, Any], ...]:
    """Validate and flatten bounded ``gh --paginate --slurp`` workflow runs."""

    pages = value if isinstance(value, list) else [value]
    if not pages or not all(isinstance(page, dict) for page in pages):
        raise ValueError("workflow-run response must contain object pages")
    records: list[dict[str, Any]] = []
    for page in pages:
        page_records = page.get("workflow_runs")
        if not isinstance(page_records, list) or not all(
            isinstance(record, dict) for record in page_records
        ):
            raise ValueError("workflow-run response contains invalid records")
        records.extend(page_records)
        if len(records) > MAX_WORKFLOW_RUN_RECORDS:
            raise ValueError("workflow-run response exceeds the bounded record limit")
    return tuple(records)


def dispatched_agents(
    request: MentionRequest,
    dispatch_client: GitHubClient,
    agents: Sequence[str] | None = None,
) -> frozenset[str]:
    """Return agents with a durable central run for this exact invocation.

    A run record proves GitHub accepted the repository dispatch even when its
    conclusion is failure. Repeating a failed invocation requires a new trusted
    source comment, which produces a different key and preserves auditable
    at-most-once behavior for each request.
    """

    candidates = tuple(request.agents if agents is None else agents)
    observed: set[str] = set()
    for agent in candidates:
        endpoint = AGENT_WORKFLOW_RUN_ENDPOINTS.get(agent)
        if endpoint is None:
            raise ValueError(f"unsupported agent: {agent}")
        response = dispatch_client.request(
            [
                endpoint,
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
        marker = agent_invocation_marker(request, agent)
        for run in _workflow_run_records(response):
            run_id = run.get("id")
            if (
                isinstance(run_id, int)
                and run_id > 0
                and run.get("event") == "repository_dispatch"
                and marker in str(run.get("display_title") or "")
            ):
                observed.add(agent)
                break
    return frozenset(observed)


def noema_payload(request: MentionRequest) -> dict[str, Any]:
    """Return the central Noema repository-dispatch request body."""

    agent = "cwl-noema-review"
    return {
        "event_type": "noema-review",
        "client_payload": {
            "target_repository": request.repository,
            "pr_number": request.pull_request_number,
            "pr_head_sha": request.pull_request_head_sha,
            "requested_agent": agent,
            "agent_invocation_key": agent_invocation_key(request, agent),
            "requested_by": request.actor,
            "source_comment_id": request.comment_id,
        },
    }


def opencode_payload(request: MentionRequest) -> dict[str, Any]:
    """Return the review-only central OpenCode scheduler dispatch body."""

    agent = "opencode-agent"
    return {
        "event_type": "merge-scheduler",
        "client_payload": {
            "target_repository": request.repository,
            "pr_number": request.pull_request_number,
            "pr_head_sha": request.pull_request_head_sha,
            "base_branch": request.pull_request_base_branch,
            "trigger_reviews": True,
            "review_dispatch_limit": "1",
            "enable_auto_merge": False,
            "update_branches": False,
            "merge_mode": "disabled",
            "requested_agent": agent,
            "agent_invocation_key": agent_invocation_key(request, agent),
            "requested_by": request.actor,
            "source_comment_id": request.comment_id,
        },
    }


def dispatch_request(
    request: MentionRequest,
    *,
    target_client: GitHubClient,
    dispatch_client: GitHubClient,
    opencode_allowlist: frozenset[str],
    dry_run: bool = False,
) -> tuple[str, ...]:
    """Dispatch only missing agents and acknowledge new work on the target PR."""

    dispatchable, rejected = eligible_agents(
        request,
        opencode_allowlist=opencode_allowlist,
    )
    if dry_run:
        handles = tuple(f"@{agent}" for agent in dispatchable)
        print(
            "DRY-RUN agent mention "
            f"repo={request.repository} pr={request.pull_request_number} "
            f"head={request.pull_request_head_sha} "
            f"dispatch={','.join(dispatchable) or 'none'} "
            f"reject={','.join(rejected) or 'none'}"
        )
        return handles

    existing = dispatched_agents(request, dispatch_client, dispatchable)
    missing = tuple(agent for agent in dispatchable if agent not in existing)
    handles = tuple(f"@{agent}" for agent in missing)
    if not missing and not rejected:
        return ()

    dispatch_endpoint = f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/dispatches"
    if "cwl-noema-review" in missing:
        dispatch_client.request(
            [dispatch_endpoint, "-X", "POST"],
            input_payload=noema_payload(request),
        )
    if "opencode-agent" in missing:
        dispatch_client.request(
            [dispatch_endpoint, "-X", "POST"],
            input_payload=opencode_payload(request),
        )

    target_api = f"repos/{request.repository}"
    target_client.request(
        [f"{target_api}/issues/comments/{request.comment_id}/reactions", "-X", "POST"],
        input_payload={"content": "eyes"},
    )
    status_parts: list[str] = []
    if handles:
        status_parts.append(f"Queued {' and '.join(handles)}")
    existing_handles = tuple(
        f"@{agent}" for agent in dispatchable if agent in existing
    )
    if existing_handles:
        status_parts.append(
            f"Already queued {' and '.join(existing_handles)} on this exact request"
        )
    if rejected:
        rejected_handles = " and ".join(f"@{agent}" for agent in rejected)
        status_parts.append(
            f"Rejected {rejected_handles}: repository is absent from "
            "OPENCODE_REPOSITORY_DISPATCH_TARGETS"
        )
    acknowledgement = (
        f"{receipt_marker(request.comment_id)}\n"
        f"{' ; '.join(status_parts)} for PR #{request.pull_request_number} at head "
        f"`{request.pull_request_head_sha}`. Central exact-key workflow runs are "
        "the durable dispatch ledger; existing review workflows remain "
        "authoritative for the final verdict and failure evidence."
    )
    target_client.request(
        [f"{target_api}/issues/{request.pull_request_number}/comments", "-X", "POST"],
        input_payload={"body": acknowledgement},
    )
    return handles


def load_event(path: str) -> dict[str, Any]:
    """Load and validate a GitHub event JSON document."""

    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("GitHub event payload must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Run the mention router for one enriched GitHub issue-comment event."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.event_path:
        parser.error("--event-path or GITHUB_EVENT_PATH is required")
    request = parse_event(load_event(args.event_path))
    if request is None:
        print("No trusted pull-request agent mention found; nothing to dispatch.")
        return 0
    target_token = os.environ.get("TARGET_REPOSITORY_TOKEN") or os.environ.get(
        "GH_TOKEN", ""
    )
    dispatch_token = os.environ.get("AGENT_DISPATCH_TOKEN") or os.environ.get(
        "GH_TOKEN", ""
    )
    allowlist = parse_repository_allowlist(
        os.environ.get("OPENCODE_REPOSITORY_DISPATCH_TARGETS", "")
    )
    dispatch_request(
        request,
        target_client=GitHubClient(target_token),
        dispatch_client=GitHubClient(dispatch_token),
        opencode_allowlist=allowlist,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
