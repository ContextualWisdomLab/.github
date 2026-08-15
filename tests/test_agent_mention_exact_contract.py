"""Pin complete v2 dispatch, reaction, and receipt contracts."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the agent-mention router under an isolated test module name."""

    module_name = "agent_mention_router_exact_contract"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def mention_request(module: ModuleType, *, agents: tuple[str, ...]):
    """Build one exact request for dispatch-contract verification."""

    return module.MentionRequest(
        repository="ContextualWisdomLab/.github",
        pull_request_number=840,
        pull_request_head_sha="a" * 40,
        pull_request_base_branch="main",
        comment_id=123,
        actor="maintainer",
        agents=agents,
        pull_request_base_sha="b" * 40,
    )


def expected_opencode_claim(request) -> dict[str, object]:
    """Return the complete canonical v2 OpenCode claim expected by GitHub."""

    return {
        "actor": request.actor,
        "agent": "opencode-agent",
        "base_branch": request.pull_request_base_branch,
        "base_sha": request.pull_request_base_sha,
        "comment_id": request.comment_id,
        "head_sha": request.pull_request_head_sha,
        "pr_number": request.pull_request_number,
        "repository": request.repository,
        "enable_auto_merge": False,
        "merge_mode": "disabled",
        "review_dispatch_limit": "1",
        "trigger_reviews": True,
        "update_branches": False,
    }


def expected_opencode_payload(request) -> dict[str, object]:
    """Return the full three-property v2 repository-dispatch envelope."""

    claim = expected_opencode_claim(request)
    invocation_key = hashlib.sha256(
        json.dumps(
            claim,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "event_type": "agent-mention-opencode",
        "client_payload": {
            "schema": "cwl.agent-invocation/v2",
            "claim": claim,
            "agent_invocation_key": invocation_key,
        },
    }


def expected_noema_payload(request) -> dict[str, object]:
    """Return the complete legacy Noema dispatch contract."""

    return {
        "event_type": "agent-mention-noema",
        "client_payload": {
            "target_repository": request.repository,
            "pr_number": request.pull_request_number,
            "pr_head_sha": request.pull_request_head_sha,
            "pr_base_sha": request.pull_request_base_sha,
            "base_branch": request.pull_request_base_branch,
            "requested_agent": "cwl-noema-review",
            "agent_invocation_key": request_module_key(
                request,
                "cwl-noema-review",
            ),
            "requested_by": request.actor,
            "source_comment_id": request.comment_id,
        },
    }


def request_module_key(request, agent: str) -> str:
    """Calculate the router's canonical invocation key independently."""

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
    return hashlib.sha256(
        json.dumps(
            claim,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


class RecordingCentralClient:
    """Record exact artifact and repository-dispatch requests."""

    def __init__(self) -> None:
        """Initialize an empty call ledger."""

        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Return an empty artifact inventory and record every request."""

        self.calls.append((list(args), input_payload))
        if args[0].endswith("/actions/artifacts"):
            return {"total_count": 0, "artifacts": []}
        return None


class ReactionDeniedClient:
    """Record target mutations while denying only the cosmetic reaction."""

    def __init__(self) -> None:
        """Initialize an empty target request ledger."""

        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Reject the reaction and accept the durable acknowledgement."""

        self.calls.append((list(args), input_payload))
        if args[0].endswith("/reactions"):
            raise RuntimeError(
                "gh api failed: Resource not accessible by integration"
            )
        return None


def artifact_lookup(module: ModuleType, request, agent: str):
    """Return the exact empty-ledger lookup call for one agent."""

    artifact_name = module.agent_ledger_artifact_name(request, agent)
    return (
        [
            "repos/ContextualWisdomLab/.github/actions/artifacts",
            "-X",
            "GET",
            "-f",
            f"name={artifact_name}",
            "-f",
            "per_page=100",
        ],
        None,
    )


def expected_acknowledgement(*, handles: str) -> str:
    """Return the exact user-facing receipt for one exact request."""

    return (
        "<!-- cwl-agent-mention-receipt:123 -->\n"
        f"Queued {handles} for PR #840 at head `{'a' * 40}`. "
        "Central exact-name Actions artifacts are the durable dispatch ledger; "
        "existing review workflows remain authoritative for the final verdict "
        "and failure evidence."
    )


def test_opencode_payload_pins_every_v2_field_and_value() -> None:
    """The v2 client payload contains exactly three fully bound properties."""

    module = load_module()
    request = mention_request(module, agents=("opencode-agent",))
    expected = expected_opencode_payload(request)

    assert module.opencode_payload(request) == expected
    client_payload = expected["client_payload"]
    assert isinstance(client_payload, dict)
    assert set(client_payload) == {
        "schema",
        "claim",
        "agent_invocation_key",
    }
    claim = client_payload["claim"]
    assert isinstance(claim, dict)
    assert claim["base_sha"] == request.pull_request_base_sha


def test_reaction_denial_pins_single_agent_requests_and_prose(capsys) -> None:
    """A denied reaction leaves the full Noema dispatch and receipt intact."""

    module = load_module()
    request = mention_request(module, agents=("cwl-noema-review",))
    central = RecordingCentralClient()
    target = ReactionDeniedClient()

    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ("@cwl-noema-review",)

    assert central.calls == [
        artifact_lookup(module, request, "cwl-noema-review"),
        (
            [
                "repos/ContextualWisdomLab/.github/dispatches",
                "-X",
                "POST",
            ],
            expected_noema_payload(request),
        ),
    ]
    acknowledgement = expected_acknowledgement(handles="@cwl-noema-review")
    assert target.calls == [
        (
            [
                "repos/ContextualWisdomLab/.github/issues/comments/123/reactions",
                "-X",
                "POST",
            ],
            {"content": "eyes"},
        ),
        (
            [
                "repos/ContextualWisdomLab/.github/issues/840/comments",
                "-X",
                "POST",
            ],
            {"body": acknowledgement},
        ),
    ]
    assert capsys.readouterr().out == (
        "::warning::Agent dispatch is durably queued, but the optional eyes "
        "reaction could not be recorded: gh api failed: Resource not accessible "
        "by integration\n"
    )


def test_reaction_denial_pins_two_agent_requests_and_prose(capsys) -> None:
    """A denied reaction preserves both dispatches and the combined receipt."""

    module = load_module()
    request = mention_request(
        module,
        agents=("cwl-noema-review", "opencode-agent"),
    )
    central = RecordingCentralClient()
    target = ReactionDeniedClient()

    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset({request.repository}),
    ) == ("@cwl-noema-review", "@opencode-agent")

    assert central.calls == [
        artifact_lookup(module, request, "cwl-noema-review"),
        artifact_lookup(module, request, "opencode-agent"),
        (
            [
                "repos/ContextualWisdomLab/.github/dispatches",
                "-X",
                "POST",
            ],
            expected_noema_payload(request),
        ),
        (
            [
                "repos/ContextualWisdomLab/.github/dispatches",
                "-X",
                "POST",
            ],
            expected_opencode_payload(request),
        ),
    ]
    acknowledgement = expected_acknowledgement(
        handles="@cwl-noema-review and @opencode-agent"
    )
    assert target.calls == [
        (
            [
                "repos/ContextualWisdomLab/.github/issues/comments/123/reactions",
                "-X",
                "POST",
            ],
            {"content": "eyes"},
        ),
        (
            [
                "repos/ContextualWisdomLab/.github/issues/840/comments",
                "-X",
                "POST",
            ],
            {"body": acknowledgement},
        ),
    ]
    assert capsys.readouterr().out == (
        "::warning::Agent dispatch is durably queued, but the optional eyes "
        "reaction could not be recorded: gh api failed: Resource not accessible "
        "by integration\n"
    )
