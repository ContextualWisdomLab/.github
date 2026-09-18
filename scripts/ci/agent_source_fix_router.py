#!/usr/bin/env python3
"""Route explicit trusted PR source-fix comments to the bounded mutation worker."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Sequence

try:
    from agent_mention_router import GitHubClient, parse_repository_allowlist
except ModuleNotFoundError:
    from scripts.ci.agent_mention_router import GitHubClient, parse_repository_allowlist

CENTRAL_AUTOMATION_REPOSITORY = "ContextualWisdomLab/.github"
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
SOURCE_FIX_PATTERN = re.compile(r"(?<![\w/-])@cwl-source-fix(?![\w/-])", re.IGNORECASE)
REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/(?!.*(?:\.\.|\.$))[A-Za-z0-9_.-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REF_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9-]+$")
LEDGER_PREFIX = "cwl-source-fix-invocation-"
RECEIPT_RE = re.compile(r"<!-- cwl-source-fix-receipt:(\d+) -->")


@dataclass(frozen=True)
class SourceFixRequest:
    """Immutable source-fix request bound to one exact PR/comment snapshot."""

    repository: str
    pull_request_number: int
    pull_request_head_sha: str
    pull_request_head_ref: str
    pull_request_base_sha: str
    pull_request_base_ref: str
    comment_id: int
    actor: str
    instruction_sha256: str


def has_source_fix_command(body: str) -> bool:
    """Return whether body contains the exact source-fix command handle."""
    return SOURCE_FIX_PATTERN.search(body) is not None


def instruction_digest(body: str) -> str:
    """Bind the complete operator instruction to one immutable dispatch claim."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _receipt_ids(comments: Sequence[dict[str, Any]]) -> frozenset[int]:
    """Return source-comment ids already acknowledged by GitHub Actions."""
    processed: set[int] = set()
    for comment in comments:
        user = comment.get("user") or {}
        if str(user.get("login") or "").casefold() != "github-actions[bot]":
            continue
        if str(user.get("type") or "").casefold() != "bot":
            continue
        processed.update(int(value) for value in RECEIPT_RE.findall(str(comment.get("body") or "")))
    return frozenset(processed)


def parse_event(event: dict[str, Any]) -> SourceFixRequest | None:
    """Validate one enriched issue-comment event and return a source-fix request."""
    issue = event.get("issue") or {}
    comment = event.get("comment") or {}
    repository = event.get("repository") or {}
    pull_request = event.get("pull_request") or {}
    if not issue.get("pull_request") or pull_request.get("state") != "open":
        return None
    if str(comment.get("user", {}).get("type", "")).casefold() == "bot":
        return None
    if str(comment.get("author_association", "")).upper() not in TRUSTED_ASSOCIATIONS:
        return None
    body = str(comment.get("body") or "")
    if not has_source_fix_command(body):
        return None

    repository_name = str(repository.get("full_name") or "").strip()
    actor = str(comment.get("user", {}).get("login") or "").strip()
    number = issue.get("number")
    comment_id = comment.get("id")
    head = pull_request.get("head") or {}
    base = pull_request.get("base") or {}
    head_sha = str(head.get("sha") or "").strip().lower()
    head_ref = str(head.get("ref") or "").strip()
    base_sha = str(base.get("sha") or "").strip().lower()
    base_ref = str(base.get("ref") or "").strip()

    if not REPOSITORY_RE.fullmatch(repository_name):
        raise ValueError("source fix is limited to ContextualWisdomLab repositories")
    if not isinstance(number, int) or number < 1:
        raise ValueError("pull request number is missing or invalid")
    if not isinstance(comment_id, int) or comment_id < 1:
        raise ValueError("comment id is missing or invalid")
    if comment_id in _receipt_ids(event.get("conversation_comments") or ()):
        return None
    if not SHA_RE.fullmatch(head_sha) or not SHA_RE.fullmatch(base_sha):
        raise ValueError("pull request head/base SHA is missing or invalid")
    if not REF_RE.fullmatch(head_ref) or not REF_RE.fullmatch(base_ref):
        raise ValueError("pull request head/base ref is missing or invalid")
    if not ACTOR_RE.fullmatch(actor):
        raise ValueError("comment actor is missing or invalid")

    return SourceFixRequest(
        repository=repository_name,
        pull_request_number=number,
        pull_request_head_sha=head_sha,
        pull_request_head_ref=head_ref,
        pull_request_base_sha=base_sha,
        pull_request_base_ref=base_ref,
        comment_id=comment_id,
        actor=actor,
        instruction_sha256=instruction_digest(body),
    )


def invocation_claim(request: SourceFixRequest) -> dict[str, object]:
    """Return the canonical claim for one write-capable source-fix request."""
    return {
        "actor": request.actor,
        "base_ref": request.pull_request_base_ref,
        "base_sha": request.pull_request_base_sha,
        "comment_id": request.comment_id,
        "head_ref": request.pull_request_head_ref,
        "head_sha": request.pull_request_head_sha,
        "instruction_sha256": request.instruction_sha256,
        "pr_number": request.pull_request_number,
        "repository": request.repository,
        "write_mode": "existing-pr-files-only",
    }


def invocation_key(request: SourceFixRequest) -> str:
    """Return the deterministic SHA-256 id for one immutable source-fix claim."""
    canonical = json.dumps(
        invocation_claim(request),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def ledger_name(request: SourceFixRequest) -> str:
    """Return the exact Actions artifact name used as the dispatch ledger key."""
    return f"{LEDGER_PREFIX}{invocation_key(request)}"


def dispatch_payload(request: SourceFixRequest) -> dict[str, Any]:
    """Return a repository_dispatch body at GitHub's 10-key payload ceiling."""
    payload = {
        "target_repository": request.repository,
        "pr_number": request.pull_request_number,
        "pr_head_sha": request.pull_request_head_sha,
        "pr_head_ref": request.pull_request_head_ref,
        "pr_base_sha": request.pull_request_base_sha,
        "pr_base_ref": request.pull_request_base_ref,
        "requested_by": request.actor,
        "source_comment_id": request.comment_id,
        "instruction_sha256": request.instruction_sha256,
        "invocation_key": invocation_key(request),
    }
    if len(payload) != 10:
        raise AssertionError("source-fix dispatch payload must contain exactly 10 keys")
    return {"event_type": "agent-source-fix", "client_payload": payload}


def _already_claimed(request: SourceFixRequest, client: GitHubClient) -> bool:
    """Return whether the central exact-name artifact already claims this request."""
    expected_name = ledger_name(request)
    response = client.request(
        [
            f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/actions/artifacts",
            "-X",
            "GET",
            "-f",
            f"name={expected_name}",
            "-f",
            "per_page=100",
        ]
    )
    if not isinstance(response, dict):
        raise ValueError("artifact response must be an object")
    total_count = response.get("total_count")
    artifacts = response.get("artifacts")
    if type(total_count) is not int or not isinstance(artifacts, list):
        raise ValueError("artifact response is malformed")
    if total_count != len(artifacts):
        raise ValueError("artifact response is truncated or inconsistent")
    live = False
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("artifact response contains a non-object record")
        if artifact.get("name") != expected_name or type(artifact.get("expired")) is not bool:
            raise ValueError("artifact response contains a mismatched record")
        live = live or not artifact["expired"]
    return live


def dispatch_request(
    request: SourceFixRequest,
    *,
    target_client: GitHubClient,
    dispatch_client: GitHubClient,
    repository_allowlist: frozenset[str],
    dry_run: bool = False,
) -> bool:
    """Queue one exact source-fix invocation and acknowledge it once."""
    allowlist = {entry.casefold() for entry in repository_allowlist}
    if request.repository.casefold() not in allowlist:
        print(
            "Rejected @cwl-source-fix: repository is absent from "
            "SOURCE_FIX_REPOSITORY_TARGETS/OPENCODE_REPOSITORY_DISPATCH_TARGETS."
        )
        return False
    if dry_run:
        print(
            "DRY-RUN source fix "
            f"repo={request.repository} pr={request.pull_request_number} "
            f"head={request.pull_request_head_sha} comment={request.comment_id}"
        )
        return True
    if _already_claimed(request, dispatch_client):
        return False

    dispatch_client.request(
        [f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/dispatches", "-X", "POST"],
        input_payload=dispatch_payload(request),
    )
    target_api = f"repos/{request.repository}"
    try:
        target_client.request(
            [f"{target_api}/issues/comments/{request.comment_id}/reactions", "-X", "POST"],
            input_payload={"content": "eyes"},
        )
    except Exception as exc:  # noqa: BLE001 - cosmetic acknowledgement only
        print(f"::warning::Source-fix acknowledgement reaction failed: {str(exc)[:1000]}")
    acknowledgement = (
        f"<!-- cwl-source-fix-receipt:{request.comment_id} -->\n"
        f"Queued `@cwl-source-fix` for PR #{request.pull_request_number} at exact head "
        f"`{request.pull_request_head_sha}`. The worker may edit only files already "
        "present in this PR diff, revalidates current write permission and exact "
        "base/head identity before mutation, and never merges the PR."
    )
    try:
        target_client.request(
            [f"{target_api}/issues/{request.pull_request_number}/comments", "-X", "POST"],
            input_payload={"body": acknowledgement},
        )
    except Exception as exc:  # noqa: BLE001 - dispatch is already durable
        print(f"::warning::Source-fix acknowledgement comment failed: {str(exc)[:1000]}")
    return True


def load_event(path: str) -> dict[str, Any]:
    """Load and validate one GitHub issue-comment event document."""
    with open(path, encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError("GitHub event payload must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    """Route one trusted explicit source-fix command from an enriched event."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-path", default=os.environ.get("GITHUB_EVENT_PATH", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if not args.event_path:
        parser.error("--event-path or GITHUB_EVENT_PATH is required")
    request = parse_event(load_event(args.event_path))
    if request is None:
        print("No trusted pull-request @cwl-source-fix command found; nothing to dispatch.")
        return 0
    target_token = os.environ.get("TARGET_REPOSITORY_TOKEN") or os.environ.get("GH_TOKEN", "")
    dispatch_token = os.environ.get("AGENT_DISPATCH_TOKEN") or os.environ.get("GH_TOKEN", "")
    allowlist_raw = os.environ.get("SOURCE_FIX_REPOSITORY_TARGETS") or os.environ.get(
        "OPENCODE_REPOSITORY_DISPATCH_TARGETS", ""
    )
    dispatch_request(
        request,
        target_client=GitHubClient(target_token),
        dispatch_client=GitHubClient(dispatch_token),
        repository_allowlist=parse_repository_allowlist(allowlist_raw),
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
