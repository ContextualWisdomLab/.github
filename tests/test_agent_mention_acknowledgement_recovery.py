"""Regression tests for post-dispatch mention acknowledgement recovery."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the central mention router from its script path."""

    module_name = "agent_mention_router_acknowledgement_recovery"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def request(module: ModuleType):
    """Build one exact trusted OpenCode mention request."""

    return module.MentionRequest(
        repository="ContextualWisdomLab/.github",
        pull_request_number=1099,
        pull_request_head_sha="a" * 40,
        pull_request_base_branch="main",
        comment_id=91,
        actor="maintainer",
        agents=("opencode-agent",),
        pull_request_base_sha="b" * 40,
    )


class FakeClient:
    """Capture API traffic while simulating ledger and UX failures."""

    def __init__(
        self,
        *,
        existing_claim: bool = False,
        fail_reaction: bool = False,
        fail_comment: bool = False,
    ) -> None:
        """Initialize deterministic response and failure controls."""

        self.existing_claim = existing_claim
        self.fail_reaction = fail_reaction
        self.fail_comment = fail_comment
        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Record one request and return or raise the configured outcome."""

        arguments = list(args)
        self.calls.append((arguments, input_payload))
        endpoint = arguments[0]
        if endpoint.endswith("/actions/artifacts"):
            if not self.existing_claim:
                return {"total_count": 0, "artifacts": []}
            name = next(
                value.removeprefix("name=")
                for value in arguments
                if value.startswith("name=")
            )
            return {
                "total_count": 1,
                "artifacts": [{"id": 17, "name": name, "expired": False}],
            }
        if endpoint.endswith("/reactions") and self.fail_reaction:
            raise RuntimeError("Resource not accessible by integration (HTTP 403)")
        if endpoint.endswith("/issues/1099/comments") and self.fail_comment:
            raise RuntimeError("comment publication failed")
        return None


def dispatch_mutations(client: FakeClient) -> list[tuple[list[str], dict | None]]:
    """Return only repository-dispatch mutation calls."""

    return [call for call in client.calls if call[0][0].endswith("/dispatches")]


def acknowledgement_comments(client: FakeClient) -> list[dict]:
    """Return published target-PR acknowledgement payloads."""

    return [
        payload
        for args, payload in client.calls
        if args[0].endswith("/issues/1099/comments") and payload is not None
    ]


def test_existing_durable_claim_heals_missing_acknowledgement() -> None:
    """A ledgered invocation is acknowledged without a duplicate dispatch."""

    module = load_module()
    central = FakeClient(existing_claim=True)
    target = FakeClient()

    assert module.dispatch_request(
        request(module),
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset({"ContextualWisdomLab/.github"}),
    ) == ()

    assert dispatch_mutations(central) == []
    comments = acknowledgement_comments(target)
    assert len(comments) == 1
    assert "Already queued @opencode-agent on this exact request" in comments[0]["body"]
    assert "cwl-agent-mention-receipt:91" in comments[0]["body"]


def test_reaction_failure_does_not_hide_successful_dispatch(capsys) -> None:
    """A cosmetic reaction 403 cannot suppress the durable acknowledgement."""

    module = load_module()
    central = FakeClient()
    target = FakeClient(fail_reaction=True)

    assert module.dispatch_request(
        request(module),
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset({"ContextualWisdomLab/.github"}),
    ) == ("@opencode-agent",)

    assert len(dispatch_mutations(central)) == 1
    assert len(acknowledgement_comments(target)) == 1
    assert "::warning::" in capsys.readouterr().out


def test_acknowledgement_comment_failure_remains_visible(capsys) -> None:
    """A cosmetic comment failure preserves durable dispatch and warning evidence."""

    module = load_module()
    central = FakeClient()
    target = FakeClient(fail_comment=True)

    assert module.dispatch_request(
        request(module),
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset({"ContextualWisdomLab/.github"}),
    ) == ("@opencode-agent",)

    assert len(dispatch_mutations(central)) == 1
    assert "durable dispatch state is preserved" in capsys.readouterr().out
