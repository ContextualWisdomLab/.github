"""Review-driven runtime regressions for the agent mention control plane."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"


def load_module() -> ModuleType:
    """Load the router under one isolated module name."""

    module_name = "agent_mention_router_review_regressions"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def request(module: ModuleType, agents=("cwl-noema-review", "opencode-agent")):
    """Build one exact invocation request."""

    return module.MentionRequest(
        "ContextualWisdomLab/Example",
        17,
        "a" * 40,
        "main",
        91,
        "maintainer",
        agents,
    )


class FakeClient:
    """Capture API requests and expose exact-name artifact inventories."""

    def __init__(self, responses=None) -> None:
        """Initialize responses and an empty call ledger."""

        self.responses = responses or {}
        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Record a call and return its registered artifact response."""

        args = list(args)
        self.calls.append((args, input_payload))
        if args[0].endswith("/actions/artifacts"):
            name = next(
                value.split("=", 1)[1]
                for value in args
                if value.startswith("name=")
            )
            return self.responses.get(
                name,
                {"total_count": 0, "artifacts": []},
            )
        return None


def test_actor_and_allowlist_validation_are_wrapper_compatible() -> None:
    """Router validation rejects actors wrappers cannot accept."""

    module = load_module()
    payload = {
        "repository": {"full_name": "ContextualWisdomLab/Example"},
        "issue": {"number": 17, "pull_request": {"url": "x"}},
        "comment": {
            "id": 91,
            "body": "@opencode-agent",
            "author_association": "MEMBER",
            "user": {"login": "bad_actor", "type": "User"},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": "a" * 40},
            "base": {"ref": "main"},
        },
    }
    with pytest.raises(ValueError, match="actor"):
        module.parse_event(payload)

    mention = request(module, ("opencode-agent",))
    assert module.eligible_agents(
        mention,
        opencode_allowlist=frozenset({"contextualwisdomlab/example"}),
    ) == (("opencode-agent",), ())


@pytest.mark.parametrize(
    ("stderr", "message"),
    [("permission denied\n details", "permission denied details"), ("", "no stderr")],
)
def test_github_client_surfaces_bounded_api_diagnostics(
    monkeypatch,
    stderr: str,
    message: str,
) -> None:
    """A failed gh call identifies the real API boundary."""

    module = load_module()
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            stdout="",
            stderr=stderr,
            returncode=1,
        ),
    )
    with pytest.raises(RuntimeError, match=message):
        module.GitHubClient("token").request(["repos/x/y"])


def test_exact_artifact_cache_bounds_api_cost() -> None:
    """Each exact artifact name is queried once per router or sweep run."""

    module = load_module()
    mention = request(module)
    name = module.agent_ledger_artifact_name(mention, "cwl-noema-review")
    client = FakeClient(
        {
            name: {
                "total_count": 1,
                "artifacts": [
                    {"id": 1, "name": name, "expired": False}
                ],
            }
        }
    )
    cache: dict[str, bool] = {}
    expected = frozenset({"cwl-noema-review"})
    assert module.dispatched_agents(
        mention,
        client,
        ledger_artifact_cache=cache,
    ) == expected
    assert module.dispatched_agents(
        mention,
        client,
        ledger_artifact_cache=cache,
    ) == expected
    artifact_calls = [
        args for args, _ in client.calls if args[0].endswith("/actions/artifacts")
    ]
    assert len(artifact_calls) == 2
    assert all("per_page=100" in args for args in artifact_calls)


def test_dispatch_cache_suppresses_same_run_retries_and_rejection_noise() -> None:
    """Accepted dispatches update the in-memory ledger before artifact visibility."""

    module = load_module()
    mention = request(module)
    target = FakeClient()
    central = FakeClient()
    cache: dict[str, bool] = {}
    allowlist = frozenset({"contextualwisdomlab/example"})

    assert module.dispatch_request(
        mention,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=allowlist,
        ledger_artifact_cache=cache,
    ) == ("@cwl-noema-review", "@opencode-agent")
    first_target_calls = len(target.calls)
    assert module.dispatch_request(
        mention,
        target_client=target,
        dispatch_client=central,
        opencode_allowlist=allowlist,
        ledger_artifact_cache=cache,
    ) == ()
    assert len(target.calls) == first_target_calls
    dispatches = [
        payload["event_type"]
        for args, payload in central.calls
        if args[0].endswith("/dispatches") and payload
    ]
    assert dispatches == ["agent-mention-noema", "agent-mention-opencode"]

    mixed = request(module)
    mixed_target = FakeClient()
    mixed_central = FakeClient()
    mixed_cache: dict[str, bool] = {}
    assert module.dispatch_request(
        mixed,
        target_client=mixed_target,
        dispatch_client=mixed_central,
        opencode_allowlist=frozenset(),
        ledger_artifact_cache=mixed_cache,
    ) == ("@cwl-noema-review",)
    first_mixed_calls = len(mixed_target.calls)
    assert module.dispatch_request(
        mixed,
        target_client=mixed_target,
        dispatch_client=mixed_central,
        opencode_allowlist=frozenset(),
        ledger_artifact_cache=mixed_cache,
    ) == ()
    assert len(mixed_target.calls) == first_mixed_calls
