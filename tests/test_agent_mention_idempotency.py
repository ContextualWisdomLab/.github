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


class RunAwareClient:
    """Fake GitHub client with workflow-run inventory and fault injection."""

    def __init__(self, *, runs=None, fail_event=None, fail_target_call=None) -> None:
        """Initialize bounded responses and optional deterministic failures."""

        self.runs = runs or {}
        self.fail_event = fail_event
        self.fail_target_call = fail_target_call
        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Return workflow runs, record mutations, or raise at a selected boundary."""

        call_number = len(self.calls) + 1
        self.calls.append((list(args), input_payload))
        endpoint = args[0]
        if endpoint.endswith("/runs"):
            return self.runs.get(endpoint, {"workflow_runs": []})
        if endpoint.endswith("/dispatches"):
            event_type = (input_payload or {}).get("event_type")
            if event_type == self.fail_event:
                raise RuntimeError(f"failed {event_type}")
        if self.fail_target_call == call_number:
            raise RuntimeError(f"failed target call {call_number}")
        return None


def workflow_run(module: ModuleType, mention_request, agent: str, run_id: int) -> dict:
    """Build one durable central workflow-run record for an exact agent request."""

    return {
        "id": run_id,
        "event": "repository_dispatch",
        "status": "completed",
        "conclusion": "failure",
        "display_title": (
            "Required review "
            f"{module.agent_invocation_marker(mention_request, agent)}"
        ),
    }


def run_inventory(module: ModuleType, mention_request, *agents: str) -> dict:
    """Return endpoint-keyed workflow-run responses for selected agents."""

    inventory = {}
    for index, agent in enumerate(agents, start=1):
        endpoint = module.AGENT_WORKFLOW_RUN_ENDPOINTS[agent]
        inventory[endpoint] = {
            "workflow_runs": [workflow_run(module, mention_request, agent, index)]
        }
    return inventory


def dispatch_events(client: RunAwareClient) -> list[str]:
    """Return repository-dispatch event types recorded by one fake client."""

    return [
        payload["event_type"]
        for args, payload in client.calls
        if args[0].endswith("/dispatches") and payload is not None
    ]


def test_invocation_key_binds_complete_request_identity() -> None:
    """The opaque key changes with agent, head, PR, repository, or source comment."""

    module = load_module()
    original = request(module)
    noema_key = module.agent_invocation_key(original, "cwl-noema-review")
    opencode_key = module.agent_invocation_key(original, "opencode-agent")
    assert re.fullmatch(r"[0-9a-f]{64}", noema_key)
    assert noema_key != opencode_key
    assert module.agent_invocation_marker(original, "cwl-noema-review") == (
        f"[cwl-agent-invocation:{noema_key}]"
    )

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


def test_existing_workflow_runs_are_per_agent_durable_evidence() -> None:
    """Queued, running, completed, or failed exact-key runs suppress only that agent."""

    module = load_module()
    mention_request = request(module)
    client = RunAwareClient(
        runs=run_inventory(module, mention_request, "cwl-noema-review")
    )
    assert module.dispatched_agents(mention_request, client) == frozenset(
        {"cwl-noema-review"}
    )

    forged = {
        module.AGENT_WORKFLOW_RUN_ENDPOINTS["cwl-noema-review"]: {
            "workflow_runs": [
                {
                    **workflow_run(
                        module, mention_request, "cwl-noema-review", 2
                    ),
                    "display_title": "forged unrelated title",
                }
            ]
        }
    }
    assert module.dispatched_agents(
        mention_request, RunAwareClient(runs=forged)
    ) == frozenset()

    malformed = RunAwareClient(
        runs={
            module.AGENT_WORKFLOW_RUN_ENDPOINTS["cwl-noema-review"]: {
                "workflow_runs": "not-a-list"
            }
        }
    )
    with pytest.raises(ValueError, match="workflow-run"):
        module.dispatched_agents(mention_request, malformed)


def test_partial_failure_retries_only_the_missing_agent() -> None:
    """A later dispatch failure never repeats an already materialized agent run."""

    module = load_module()
    mention_request = request(module)
    target = RunAwareClient()
    first = RunAwareClient(fail_event="agent-mention-opencode")

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

    retry = RunAwareClient(
        runs=run_inventory(module, mention_request, "cwl-noema-review")
    )
    assert module.dispatch_request(
        mention_request,
        target_client=RunAwareClient(),
        dispatch_client=retry,
        opencode_allowlist=frozenset({mention_request.repository}),
    ) == ("@opencode-agent",)
    assert dispatch_events(retry) == ["agent-mention-opencode"]


def test_reaction_or_ack_failure_cannot_redispatch_completed_agents() -> None:
    """Target-repository UX failure is separate from durable dispatch evidence."""

    module = load_module()
    mention_request = request(module)
    central = RunAwareClient()
    failing_target = RunAwareClient(fail_target_call=1)
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

    retry = RunAwareClient(
        runs=run_inventory(
            module,
            mention_request,
            "cwl-noema-review",
            "opencode-agent",
        )
    )
    retry_target = RunAwareClient(fail_target_call=1)
    assert module.dispatch_request(
        mention_request,
        target_client=retry_target,
        dispatch_client=retry,
        opencode_allowlist=frozenset({mention_request.repository}),
    ) == ()
    assert dispatch_events(retry) == []
    assert retry_target.calls == []


def test_exact_run_inventory_accepts_paginated_slurp_shape() -> None:
    """The bounded parser handles gh --paginate --slurp pages deterministically."""

    module = load_module()
    mention_request = request(module)
    endpoint = module.AGENT_WORKFLOW_RUN_ENDPOINTS["opencode-agent"]
    client = RunAwareClient(
        runs={
            endpoint: [
                {"workflow_runs": []},
                {
                    "workflow_runs": [
                        workflow_run(module, mention_request, "opencode-agent", 9)
                    ]
                },
            ]
        }
    )
    assert module.dispatched_agents(mention_request, client) == frozenset(
        {"opencode-agent"}
    )
