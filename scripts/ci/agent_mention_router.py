#!/usr/bin/env python3
"""Route trusted pull-request comment mentions to CWL review agents.

The router is intentionally small and fail-closed. It accepts only comments on
pull requests from trusted repository participants, recognizes exact agent
mentions, acknowledges the request, and emits repository-dispatch events that
reuse the existing Noema and OpenCode review pipelines.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Any, Sequence


TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
MENTION_PATTERNS = {
    "cwl-noema-review": re.compile(r"(?<![A-Za-z0-9_-])@cwl-noema-review(?![A-Za-z0-9_-])", re.IGNORECASE),
    "opencode-agent": re.compile(r"(?<![A-Za-z0-9_-])@opencode-agent(?![A-Za-z0-9_-])", re.IGNORECASE),
}


@dataclass(frozen=True)
class MentionRequest:
    """Validated agent-mention request extracted from one issue comment event."""

    repository: str
    pull_request_number: int
    pull_request_head_sha: str
    comment_id: int
    actor: str
    agents: tuple[str, ...]


def parse_event(event: dict[str, Any]) -> MentionRequest | None:
    """Return a validated mention request, or ``None`` for an ignored event."""

    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    repository = event.get("repository") or {}

    if not issue.get("pull_request"):
        return None
    if str(comment.get("user", {}).get("type", "")).casefold() == "bot":
        return None
    if str(comment.get("author_association", "")).upper() not in TRUSTED_ASSOCIATIONS:
        return None

    body = str(comment.get("body") or "")
    agents = tuple(name for name, pattern in MENTION_PATTERNS.items() if pattern.search(body))
    if not agents:
        return None

    repository_name = str(repository.get("full_name") or "").strip()
    actor = str(comment.get("user", {}).get("login") or "").strip()
    head_sha = str((event.get("pull_request") or {}).get("head", {}).get("sha") or "").strip()
    number = issue.get("number")
    comment_id = comment.get("id")

    if not re.fullmatch(r"ContextualWisdomLab/[A-Za-z0-9_.-]+", repository_name):
        raise ValueError("agent mentions are limited to ContextualWisdomLab repositories")
    if not isinstance(number, int) or number < 1:
        raise ValueError("pull request number is missing or invalid")
    if not isinstance(comment_id, int) or comment_id < 1:
        raise ValueError("comment id is missing or invalid")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise ValueError("pull request head SHA is missing or invalid")
    if not actor:
        raise ValueError("comment actor is missing")

    return MentionRequest(
        repository=repository_name,
        pull_request_number=number,
        pull_request_head_sha=head_sha.lower(),
        comment_id=comment_id,
        actor=actor,
        agents=agents,
    )


def gh_api(args: Sequence[str], *, input_payload: dict[str, Any] | None = None) -> None:
    """Invoke ``gh api`` with an optional JSON request payload."""

    command = ["gh", "api", *args]
    if input_payload is not None:
        command.extend(["--input", "-"])
    subprocess.run(
        command,
        input=None if input_payload is None else json.dumps(input_payload),
        text=True,
        check=True,
    )


def dispatch(request: MentionRequest) -> None:
    """Acknowledge and dispatch all agents requested by a validated comment."""

    repo_api = f"repos/{request.repository}"
    gh_api(
        [f"{repo_api}/issues/comments/{request.comment_id}/reactions", "-X", "POST"],
        input_payload={"content": "eyes"},
    )

    dispatched: list[str] = []
    if "cwl-noema-review" in request.agents:
        gh_api(
            [f"{repo_api}/dispatches", "-X", "POST"],
            input_payload={
                "event_type": "noema-review",
                "client_payload": {
                    "target_repository": request.repository,
                    "pr_number": request.pull_request_number,
                    "pr_head_sha": request.pull_request_head_sha,
                    "requested_by": request.actor,
                    "source_comment_id": request.comment_id,
                },
            },
        )
        dispatched.append("@cwl-noema-review")

    if "opencode-agent" in request.agents:
        gh_api(
            [f"{repo_api}/dispatches", "-X", "POST"],
            input_payload={
                "event_type": "merge-scheduler",
                "client_payload": {
                    "target_repository": request.repository,
                    "pr_number": request.pull_request_number,
                    "pr_head_sha": request.pull_request_head_sha,
                    "trigger_reviews": True,
                    "review_dispatch_limit": 1,
                    "requested_agent": "opencode-agent",
                    "requested_by": request.actor,
                    "source_comment_id": request.comment_id,
                },
            },
        )
        dispatched.append("@opencode-agent")

    acknowledgement = (
        f"Queued {' and '.join(dispatched)} for PR #{request.pull_request_number} "
        f"at head `{request.pull_request_head_sha}`. The existing review workflows "
        "will post their normal verdict or failure evidence."
    )
    gh_api(
        [f"{repo_api}/issues/{request.pull_request_number}/comments", "-X", "POST"],
        input_payload={"body": acknowledgement},
    )


def load_event(path: str) -> dict[str, Any]:
    """Load and validate a GitHub event JSON document."""

    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("GitHub event payload must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Run the mention router for one GitHub issue-comment event."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    args = parser.parse_args(argv)
    if not args.event_path:
        parser.error("--event-path or GITHUB_EVENT_PATH is required")

    request = parse_event(load_event(args.event_path))
    if request is None:
        print("No trusted pull-request agent mention found; nothing to dispatch.")
        return 0
    dispatch(request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
