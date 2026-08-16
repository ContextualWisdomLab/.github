"""Regression tests for non-authoritative agent-mention reactions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the agent-mention router under an isolated test module name."""

    module_name = "agent_mention_router_reaction_resilience"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class CentralClient:
    """Capture durable dispatch and artifact-ledger requests."""

    def __init__(self) -> None:
        """Initialize an empty request ledger."""

        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Return an empty artifact inventory and record all requests."""

        self.calls.append((list(args), input_payload))
        if args[0].endswith("/actions/artifacts"):
            return {"total_count": 0, "artifacts": []}
        return None


class ReactionDeniedClient:
    """Model a token that may comment but cannot add issue-comment reactions."""

    def __init__(self) -> None:
        """Initialize an empty target-repository request ledger."""

        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Reject only the cosmetic reaction while allowing the durable receipt."""

        self.calls.append((list(args), input_payload))
        if args[0].endswith("/reactions"):
            raise RuntimeError("gh api failed: Resource not accessible by integration")
        return None


def test_reaction_403_does_not_discard_durable_dispatch(capsys) -> None:
    """A cosmetic reaction denial must not fail an already queued review."""

    module = load_module()
    request = module.MentionRequest(
        repository="ContextualWisdomLab/.github",
        pull_request_number=840,
        pull_request_head_sha="a" * 40,
        pull_request_base_branch="main",
        comment_id=123,
        actor="maintainer",
        agents=("cwl-noema-review",),
        pull_request_base_sha="b" * 40,
    )
    target = ReactionDeniedClient()
    central = CentralClient()

    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ("@cwl-noema-review",)

    dispatches = [
        payload
        for args, payload in central.calls
        if args[0].endswith("/dispatches") and payload is not None
    ]
    assert [payload["event_type"] for payload in dispatches] == [
        "agent-mention-noema"
    ]
    assert target.calls[0][0][0].endswith("/reactions")
    assert target.calls[1][0][0].endswith("/issues/840/comments")
    assert "cwl-agent-mention-receipt:123" in target.calls[1][1]["body"]
    assert "optional eyes reaction could not be recorded" in capsys.readouterr().out
