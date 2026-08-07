"""Regression coverage for rejection-only agent mentions."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the router module from its script path."""

    module_name = "agent_mention_router_rejection_idempotency"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FakeClient:
    """Capture bounded GitHub API calls for one router invocation."""

    def __init__(self) -> None:
        """Initialize an empty request ledger."""

        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Record a request and return an empty workflow-run inventory."""

        self.calls.append((list(args), input_payload))
        if args[0].endswith("/runs"):
            return {"workflow_runs": []}
        return None


def test_rejected_only_request_is_mutation_free() -> None:
    """A disallowed OpenCode mention never creates repeatable target mutations."""

    module = load_module()
    request = module.MentionRequest(
        "ContextualWisdomLab/example",
        17,
        "a" * 40,
        "main",
        91,
        "maintainer",
        ("opencode-agent",),
    )
    target = FakeClient()
    central = FakeClient()

    assert module.dispatch_request(
        request,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=frozenset(),
    ) == ()
    assert target.calls == []
    assert central.calls == []
