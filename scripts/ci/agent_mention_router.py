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
LEDGER_ARTIFACTS_ENDPOINT = (
    f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/actions/artifacts"
)
LEDGER_ARTIFACT_PREFIX = "cwl-agent-invocation-"
REPOSITORY_RE = re.compile(r"^ContextualWisdomLab/[A-Za-z0-9_.-]+$")
HEAD_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
BASE_BRANCH_RE = re.compile(r"^(?!-)[A-Za-z0-9._/-]+$")
ACTOR_RE = re.compile(r"^[A-Za-z0-9-]+$")
RECEIPT_RE = re.compile(r"<!-- cwl-agent-mention-receipt:(\d+) -->")


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
    pull_request_base_sha: str = ""


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
            shell=False,
            check=False,
            env=environment,
        )
        return_code = int(getattr(completed, "returncode", 0))
        if return_code:
            diagnostic = " ".join(
                str(getattr(completed, "stderr", "") or "").split()
            )
            if not diagnostic:
                diagnostic = "no stderr output"
            raise RuntimeError(
                f"gh api failed with exit code {return_code}: {diagnostic[:2000]}"
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
    acknowledgement. Central exact-name Actions artifacts remain authoritative
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
    base = pull_request.get("base") or {}
    base_branch = str(base.get("ref") or "").strip()
    base_sha = str(base.get("sha") or "").strip()
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
    if not HEAD_SHA_RE.fullmatch(base_sha):
        raise ValueError("pull request base SHA is missing or invalid")
    if not ACTOR_RE.fullmatch(actor):
        raise ValueError("comment actor is missing or invalid")
    return MentionRequest(
        repository_name,
        number,
        head_sha.lower(),
        base_branch,
        comment_id,
        actor,
        agents,
        pull_request_base_sha=base_sha.lower(),
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
        normalized_allowlist = {entry.casefold() for entry in opencode_allowlist}
        if request.repository.casefold() in normalized_allowlist:
            dispatchable.append("opencode-agent")
        else:
            rejected.append("opencode-agent")
    return tuple(dispatchable), tuple(rejected)


def agent_invocation_claim(
    request: MentionRequest,
    agent: str,
) -> dict[str, object]:
    """Return the complete canonical security claim for one agent dispatch."""

    if agent not in MENTION_PATTERNS:
        raise ValueError(f"unsupported agent: {agent}")
    claim: dict[str, object] = {
        "actor": request.actor,
        "agent": agent,
        "base_branch": request.pull_request_base_branch,
        "base_sha": request.pull_request_base_sha,
        "comment_id": request.comment_id,
        "head_sha": request.pull_request_head_sha,
        "pr_number": request.pull_request_number,
        "repository": request.repository,
    }
    if agent == "opencode-agent":
        claim.update(
            {
                "enable_auto_merge": False,
                "merge_mode": "disabled",
                "review_dispatch_limit": "1",
                "trigger_reviews": True,
                "update_branches": False,
            }
        )
    return claim


def agent_invocation_key(request: MentionRequest, agent: str) -> str:
    """Return a deterministic opaque key for one exact agent invocation.

    The key binds repository, pull request, exact head and base identities,
    requested agent, source comment, requesting actor, and every downstream
    behavior flag. It contains no credential or provider response and is safe
    to place in workflow and artifact names.
    """

    canonical = json.dumps(
        agent_invocation_claim(request, agent),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def agent_invocation_marker(request: MentionRequest, agent: str) -> str:
    """Return the exact human-readable workflow-run marker for one invocation."""

    return f"[cwl-agent-invocation:{agent_invocation_key(request, agent)}]"


def agent_ledger_artifact_name(request: MentionRequest, agent: str) -> str:
    """Return the exact-name durable artifact ledger key for one invocation."""

    return f"{LEDGER_ARTIFACT_PREFIX}{agent_invocation_key(request, agent)}"


def _artifact_records(
    value: Any,
    *,
    expected_name: str,
) -> tuple[dict[str, Any], ...]:
    """Validate one exact-name repository artifact response and return live claims.

    The server-side ``name`` filter makes this response directly addressable by
    invocation key. Any malformed, mismatched, truncated, or ambiguous response
    fails closed rather than being interpreted as permission to redispatch.
    """

    if not isinstance(value, dict):
        raise ValueError("artifact response must be an object")
    total_count = value.get("total_count")
    artifacts = value.get("artifacts")
    if type(total_count) is not int or total_count < 0:
        raise ValueError("artifact response has an invalid total_count")
    if not isinstance(artifacts, list):
        raise ValueError("artifact response has an invalid artifacts collection")
    if total_count != len(artifacts):
        raise ValueError("artifact response is truncated or internally inconsistent")

    live: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ValueError("artifact response contains a non-object record")
        artifact_id = artifact.get("id")
        name = artifact.get("name")
        expired = artifact.get("expired")
        if type(artifact_id) is not int or artifact_id < 1:
            raise ValueError("artifact response contains an invalid artifact id")
        if not isinstance(name, str) or name != expected_name:
            raise ValueError("artifact response contains a mismatched artifact name")
        if type(expired) is not bool:
            raise ValueError("artifact response contains an invalid expired flag")
        if not expired:
            live.append(artifact)
    return tuple(live)


def dispatched_agents(
    request: MentionRequest,
    dispatch_client: GitHubClient,
    agents: Sequence[str] | None = None,
    *,
    ledger_artifact_cache: dict[str, bool] | None = None,
) -> frozenset[str]:
    """Return agents with a durable exact-name artifact for this invocation.

    Each candidate uses the repository artifact endpoint's exact ``name`` filter,
    avoiding workflow-run enumeration and its filtered-result cap. A caller-owned
    cache bounds repeated API work during one local route or organization sweep.
    """

    candidates = tuple(request.agents if agents is None else agents)
    observed: set[str] = set()
    artifact_cache = (
        ledger_artifact_cache if ledger_artifact_cache is not None else {}
    )
    for agent in candidates:
        artifact_name = agent_ledger_artifact_name(request, agent)
        if artifact_name not in artifact_cache:
            response = dispatch_client.request(
                [
                    LEDGER_ARTIFACTS_ENDPOINT,
                    "-X",
                    "GET",
                    "-f",
                    f"name={artifact_name}",
                    "-f",
                    "per_page=100",
                ]
            )
            artifact_cache[artifact_name] = bool(
                _artifact_records(response, expected_name=artifact_name)
            )
        if artifact_cache[artifact_name]:
            observed.add(agent)
    return frozenset(observed)


def noema_payload(request: MentionRequest) -> dict[str, Any]:
    """Return the durable Noema wrapper dispatch request body."""

    agent = "cwl-noema-review"
    return {
        "event_type": "agent-mention-noema",
        "client_payload": {
            "target_repository": request.repository,
            "pr_number": request.pull_request_number,
            "pr_head_sha": request.pull_request_head_sha,
            "pr_base_sha": request.pull_request_base_sha,
            "base_branch": request.pull_request_base_branch,
            "requested_agent": agent,
            "agent_invocation_key": agent_invocation_key(request, agent),
            "requested_by": request.actor,
            "source_comment_id": request.comment_id,
        },
    }


def opencode_payload(request: MentionRequest) -> dict[str, Any]:
    """Return the durable review-only OpenCode wrapper dispatch body."""

    agent = "opencode-agent"
    claim = agent_invocation_claim(request, agent)
    return {
        "event_type": "agent-mention-opencode",
        "client_payload": {
            "target_repository": request.repository,
            "pr_number": request.pull_request_number,
            "pr_head_sha": request.pull_request_head_sha,
            "pr_base_sha": request.pull_request_base_sha,
            "base_branch": request.pull_request_base_branch,
            "trigger_reviews": claim["trigger_reviews"],
            "review_dispatch_limit": claim["review_dispatch_limit"],
            "enable_auto_merge": claim["enable_auto_merge"],
            "update_branches": claim["update_branches"],
            "merge_mode": claim["merge_mode"],
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
    ledger_artifact_cache: dict[str, bool] | None = None,
) -> tuple[str, ...]:
    """Dispatch missing agents and acknowledge only newly queued work."""

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

    existing = dispatched_agents(
        request,
        dispatch_client,
        dispatchable,
        ledger_artifact_cache=ledger_artifact_cache,
    )
    missing = tuple(agent for agent in dispatchable if agent not in existing)
    handles = tuple(f"@{agent}" for agent in missing)
    if not missing:
        if rejected:
            print(
                "Rejected agent mention without target mutation "
                f"repo={request.repository} pr={request.pull_request_number} "
                f"comment={request.comment_id} "
                f"agents={','.join(rejected)}"
            )
        return ()

    dispatch_endpoint = f"repos/{CENTRAL_AUTOMATION_REPOSITORY}/dispatches"
    if "cwl-noema-review" in missing:
        agent = "cwl-noema-review"
        dispatch_client.request(
            [dispatch_endpoint, "-X", "POST"],
            input_payload=noema_payload(request),
        )
        if ledger_artifact_cache is not None:
            ledger_artifact_cache[agent_ledger_artifact_name(request, agent)] = True
    if "opencode-agent" in missing:
        agent = "opencode-agent"
        dispatch_client.request(
            [dispatch_endpoint, "-X", "POST"],
            input_payload=opencode_payload(request),
        )
        if ledger_artifact_cache is not None:
            ledger_artifact_cache[agent_ledger_artifact_name(request, agent)] = True

    target_api = f"repos/{request.repository}"
    target_client.request(
        [
            f"{target_api}/issues/comments/{request.comment_id}/reactions",
            "-X",
            "POST",
        ],
        input_payload={"content": "eyes"},
    )
    status_parts = [f"Queued {' and '.join(handles)}"]
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
        f"`{request.pull_request_head_sha}`. Central exact-name Actions artifacts "
        "are the durable dispatch ledger; existing review workflows remain "
        "authoritative for the final verdict and failure evidence."
    )
    target_client.request(
        [
            f"{target_api}/issues/{request.pull_request_number}/comments",
            "-X",
            "POST",
        ],
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
