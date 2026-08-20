"""Regression tests for durable per-agent mention dispatch idempotency."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the router module from its script path for isolated tests."""

    module_name = "agent_mention_router_idempotency"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def request(module: ModuleType):
    """Build one request containing both supported review agents."""

    return module.MentionRequest(
        "ContextualWisdomLab/inkspan",
        65,
        "a" * 40,
        "main",
        12345,
        "maintainer",
        ("cwl-noema-review", "opencode-agent"),
    )


class ArtifactAwareClient:
    """Fake GitHub client with exact artifact inventory and fault injection."""

    def __init__(
        self,
        *,
        artifacts=None,
        fail_event=None,
        fail_target_call=None,
    ) -> None:
        """Initialize bounded responses and optional deterministic failures."""

        self.artifacts = artifacts or {}
        self.fail_event = fail_event
        self.fail_target_call = fail_target_call
        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Return exact artifacts, record mutations, or raise at one boundary."""

        call_number = len(self.calls) + 1
        args = list(args)
        self.calls.append((args, input_payload))
        endpoint = args[0]
        if endpoint.endswith("/actions/artifacts"):
            name = next(
                value.split("=", 1)[1]
                for value in args
                if value.startswith("name=")
            )
            return self.artifacts.get(
                name,
                {"total_count": 0, "artifacts": []},
            )
        if endpoint.endswith("/dispatches"):
            event_type = (input_payload or {}).get("event_type")
            if event_type == self.fail_event:
                raise RuntimeError(f"failed {event_type}")
        if self.fail_target_call == call_number:
            raise RuntimeError(f"failed target call {call_number}")
        return None


def artifact(module: ModuleType, mention_request, agent: str, artifact_id: int) -> dict:
    """Build one live exact-name artifact record for an agent request."""

    return {
        "id": artifact_id,
        "name": module.agent_ledger_artifact_name(mention_request, agent),
        "expired": False,
    }


def artifact_inventory(module: ModuleType, mention_request, *agents: str) -> dict:
    """Return artifact-name-keyed responses for selected agents."""

    inventory = {}
    for index, agent in enumerate(agents, start=1):
        name = module.agent_ledger_artifact_name(mention_request, agent)
        inventory[name] = {
            "total_count": 1,
            "artifacts": [artifact(module, mention_request, agent, index)],
        }
    return inventory


def dispatch_events(client: ArtifactAwareClient) -> list[str]:
    """Return repository-dispatch event types recorded by one fake client."""

    return [
        payload["event_type"]
        for args, payload in client.calls
        if args[0].endswith("/dispatches") and payload is not None
    ]


def test_invocation_key_binds_complete_request_identity() -> None:
    """The opaque key changes with agent, head, PR, repository, or comment."""

    module = load_module()
    original = request(module)
    noema_key = module.agent_invocation_key(original, "cwl-noema-review")
    opencode_key = module.agent_invocation_key(original, "opencode-agent")
    assert re.fullmatch(r"[0-9a-f]{64}", noema_key)
    assert noema_key != opencode_key
    assert module.agent_invocation_marker(original, "cwl-noema-review") == (
        f"[cwl-agent-invocation:{noema_key}]"
    )
    assert module.agent_ledger_artifact_name(
        original, "cwl-noema-review"
    ).endswith(noema_key)

    changed_values = (
        module.MentionRequest(
            "ContextualWisdomLab/naruon",
            original.pull_request_number,
            original.pull_request_head_sha,
            original.pull_request_base_branch,
            original.comment_id,
            original.actor,
            original.agents,
        ),
        module.MentionRequest(
            original.repository,
            original.pull_request_number + 1,
            original.pull_request_head_sha,
            original.pull_request_base_branch,
            original.comment_id,
            original.actor,
            original.agents,
        ),
        module.MentionRequest(
            original.repository,
            original.pull_request_number,
            "b" * 40,
            original.pull_request_base_branch,
            original.comment_id,
            original.actor,
            original.agents,
        ),
        module.MentionRequest(
            original.repository,
            original.pull_request_number,
            original.pull_request_head_sha,
            original.pull_request_base_branch,
            original.comment_id + 1,
            original.actor,
            original.agents,
        ),
    )
    assert all(
        module.agent_invocation_key(changed, "cwl-noema-review") != noema_key
        for changed in changed_values
    )
    with pytest.raises(ValueError, match="unsupported agent"):
        module.agent_invocation_key(original, "unknown-agent")


def test_payloads_carry_exact_agent_invocation_identity() -> None:
    """Both durable wrappers receive the same deterministic request identity."""

    module = load_module()
    mention_request = request(module)
    noema_body = module.noema_payload(mention_request)
    opencode_body = module.opencode_payload(mention_request)
    assert noema_body["event_type"] == "agent-mention-noema"
    assert opencode_body["event_type"] == "agent-mention-opencode"
    noema = noema_body["client_payload"]
    opencode = opencode_body["client_payload"]

    assert noema["requested_agent"] == "cwl-noema-review"
    assert noema["agent_invocation_key"] == module.agent_invocation_key(
        mention_request, "cwl-noema-review"
    )
    assert opencode["requested_agent"] == "opencode-agent"
    assert opencode["agent_invocation_key"] == module.agent_invocation_key(
        mention_request, "opencode-agent"
    )
    for payload in (noema, opencode):
        assert payload["target_repository"] == mention_request.repository
        assert payload["pr_number"] == mention_request.pull_request_number
        assert payload["pr_head_sha"] == mention_request.pull_request_head_sha
        assert payload["source_comment_id"] == mention_request.comment_id


def test_existing_artifacts_are_per_agent_durable_evidence() -> None:
    """A live exact-name artifact suppresses only its matching agent."""

    module = load_module()
    mention_request = request(module)
    client = ArtifactAwareClient(
        artifacts=artifact_inventory(module, mention_request, "cwl-noema-review")
    )
    assert module.dispatched_agents(mention_request, client) == frozenset(
        {"cwl-noema-review"}
    )

    with pytest.raises(ValueError, match="artifact"):
        module.dispatched_agents(
            mention_request,
            ArtifactAwareClient(
                artifacts={
                    module.agent_ledger_artifact_name(
                        mention_request, "cwl-noema-review"
                    ): {"total_count": 1, "artifacts": "not-a-list"}
                }
            ),
        )


def test_artifact_inventory_edge_cases_fail_closed() -> None:
    """Malformed, inconsistent, and unsupported evidence fails safely."""

    module = load_module()
    mention_request = request(module)
    expected_name = module.agent_ledger_artifact_name(
        mention_request, "cwl-noema-review"
    )
    malformed = (
        None,
        [],
        {"total_count": True, "artifacts": []},
        {"total_count": -1, "artifacts": []},
        {"total_count": 0, "artifacts": "bad"},
        {"total_count": 1, "artifacts": []},
        {"total_count": 1, "artifacts": ["bad"]},
        {"total_count": 1, "artifacts": [{"id": True, "name": expected_name, "expired": False}]},
        {"total_count": 1, "artifacts": [{"id": 0, "name": expected_name, "expired": False}]},
        {"total_count": 1, "artifacts": [{"id": 1, "name": "wrong", "expired": False}]},
        {"total_count": 1, "artifacts": [{"id": 1, "name": expected_name, "expired": 0}]},
    )
    for value in malformed:
        with pytest.raises(ValueError, match="artifact"):
            module._artifact_records(value, expected_name=expected_name)

    assert module._artifact_records(
        {"total_count": 0, "artifacts": []},
        expected_name=expected_name,
    ) == ()
    assert module._artifact_records(
        {
            "total_count": 1,
            "artifacts": [
                {"id": 1, "name": expected_name, "expired": True}
            ],
        },
        expected_name=expected_name,
    ) == ()

    with pytest.raises(ValueError, match="unsupported agent"):
        module.dispatched_agents(
            mention_request,
            ArtifactAwareClient(),
            agents=("unknown-agent",),
        )


def test_partial_failure_retries_only_the_missing_agent() -> None:
    """A later dispatch failure never repeats an already claimed agent."""

    module = load_module()
    mention_request = request(module)
    target = ArtifactAwareClient()
    first = ArtifactAwareClient(fail_event="agent-mention-opencode")

    with pytest.raises(RuntimeError, match="agent-mention-opencode"):
        module.dispatch_request(
            mention_request,
            target_client=target,
            dispatch_client=first,
            opencode_allowlist=frozenset({mention_request.repository}),
        )
    assert dispatch_events(first) == [
        "agent-mention-noema",
        "agent-mention-opencode",
    ]

    retry = ArtifactAwareClient(
        artifacts=artifact_inventory(
            module,
            mention_request,
            "cwl-noema-review",
        )
    )
    assert module.dispatch_request(
        mention_request,
        target_client=ArtifactAwareClient(),
        dispatch_client=retry,
        opencode_allowlist=frozenset({mention_request.repository}),
    ) == ("@opencode-agent",)
    assert dispatch_events(retry) == ["agent-mention-opencode"]


def test_reaction_or_ack_failure_cannot_redispatch_completed_agents() -> None:
    """Target-repository UX failure is separate from durable dispatch evidence."""

    module = load_module()
    mention_request = request(module)
    central = ArtifactAwareClient()
    failing_target = ArtifactAwareClient(fail_target_call=1)
    with pytest.raises(RuntimeError, match="target call"):
        module.dispatch_request(
            mention_request,
            target_client=failing_target,
            dispatch_client=central,
            opencode_allowlist=frozenset({mention_request.repository}),
        )
    assert dispatch_events(central) == [
        "agent-mention-noema",
        "agent-mention-opencode",
    ]

    retry = ArtifactAwareClient(
        artifacts=artifact_inventory(
            module,
            mention_request,
            "cwl-noema-review",
            "opencode-agent",
        )
    )
    retry_target = ArtifactAwareClient(fail_target_call=1)
    assert module.dispatch_request(
        mention_request,
        target_client=retry_target,
        dispatch_client=retry,
        opencode_allowlist=frozenset({mention_request.repository}),
    ) == ()
    assert dispatch_events(retry) == []
    assert retry_target.calls == []
