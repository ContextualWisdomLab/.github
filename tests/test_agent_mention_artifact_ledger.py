"""Regression tests for the exact-name Actions artifact invocation ledger."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"
NOEMA_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-noema-dispatch.yml"
OPENCODE_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"
DOC = ROOT / "docs" / "automation" / "review-agent-comment-invocation.md"
UPLOAD_ARTIFACT_SHA = "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"


def load_module() -> ModuleType:
    """Load the router module from its script path."""

    module_name = "agent_mention_router_artifact_ledger"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def request(module: ModuleType):
    """Build one exact request containing both supported agents."""

    return module.MentionRequest(
        "ContextualWisdomLab/example",
        17,
        "a" * 40,
        "main",
        91,
        "maintainer",
        ("cwl-noema-review", "opencode-agent"),
    )


def artifact(module: ModuleType, mention, agent: str, *, expired: bool = False) -> dict:
    """Build one exact-name artifact record for an invocation."""

    return {
        "id": 7,
        "name": module.agent_ledger_artifact_name(mention, agent),
        "expired": expired,
        "created_at": "2026-08-06T12:00:00Z",
        "expires_at": "2026-09-05T12:00:00Z",
    }


class ArtifactClient:
    """Return artifact inventories while rejecting workflow-run scans."""

    def __init__(self, responses=None) -> None:
        """Initialize exact artifact-name responses and a request ledger."""

        self.responses = responses or {}
        self.calls: list[tuple[list[str], dict | None]] = []

    def request(self, args, *, input_payload=None):
        """Return a name-filtered artifact response for one API call."""

        args = list(args)
        self.calls.append((args, input_payload))
        if args[0].endswith("/runs"):
            raise AssertionError("workflow-run listings are not a durable ledger")
        if args[0].endswith("/actions/artifacts"):
            name = next(
                value.split("=", 1)[1]
                for value in args
                if value.startswith("name=")
            )
            return self.responses.get(name, {"total_count": 0, "artifacts": []})
        return None


def test_artifact_name_is_exact_key_addressable() -> None:
    """The durable ledger name contains one complete invocation digest."""

    module = load_module()
    mention = request(module)
    noema_name = module.agent_ledger_artifact_name(mention, "cwl-noema-review")
    opencode_name = module.agent_ledger_artifact_name(mention, "opencode-agent")

    assert re.fullmatch(r"cwl-agent-invocation-[0-9a-f]{64}", noema_name)
    assert noema_name != opencode_name
    assert noema_name.endswith(
        module.agent_invocation_key(mention, "cwl-noema-review")
    )


def test_exact_artifact_lookup_is_cached_without_workflow_run_pagination() -> None:
    """Each exact artifact name is queried once and reused for the sweep run."""

    module = load_module()
    mention = request(module)
    noema_name = module.agent_ledger_artifact_name(mention, "cwl-noema-review")
    client = ArtifactClient(
        {
            noema_name: {
                "total_count": 1,
                "artifacts": [artifact(module, mention, "cwl-noema-review")],
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
    assert all(any(value.startswith("name=") for value in args) for args in artifact_calls)
    assert all(not args[0].endswith("/runs") for args, _ in client.calls)


def test_artifact_inventory_validation_fails_closed() -> None:
    """Malformed, mismatched, or expired artifact evidence is never trusted."""

    module = load_module()
    mention = request(module)
    name = module.agent_ledger_artifact_name(mention, "cwl-noema-review")

    for malformed in (
        None,
        [],
        {"total_count": "1", "artifacts": []},
        {"total_count": 1, "artifacts": "bad"},
        {"total_count": 1, "artifacts": [{}]},
        {
            "total_count": 1,
            "artifacts": [{"id": 1, "name": "wrong", "expired": False}],
        },
    ):
        with pytest.raises(ValueError, match="artifact"):
            module._artifact_records(malformed, expected_name=name)

    assert module._artifact_records(
        {"total_count": 1, "artifacts": [artifact(module, mention, "cwl-noema-review", expired=True)]},
        expected_name=name,
    ) == ()


def test_thousand_workflow_runs_cannot_truncate_exact_ledger_lookup() -> None:
    """The router uses an exact-name endpoint rather than the capped run search."""

    module = load_module()
    mention = request(module)
    client = ArtifactClient()

    assert module.dispatched_agents(mention, client) == frozenset()
    assert len(client.calls) == 2
    assert all(call[0][0].endswith("/actions/artifacts") for call in client.calls)


def test_wrappers_claim_the_artifact_before_forwarding() -> None:
    """Both wrappers upload a 30-day immutable claim before repository dispatch."""

    for path in (NOEMA_WORKFLOW, OPENCODE_WORKFLOW):
        text = path.read_text(encoding="utf-8")
        assert "actions/artifacts" in text
        assert "name=${LEDGER_ARTIFACT_NAME}" in text
        assert f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}" in text
        assert "name: cwl-agent-invocation-${{ env.INVOCATION_KEY }}" in text
        assert "retention-days: 30" in text
        assert text.index("actions/upload-artifact@") < text.index(
            "Forward once to the authoritative"
        )
        assert "workflow_runs" not in text


def test_doctoring_records_artifact_ledger_contract() -> None:
    """Operator documentation cites the exact-name artifact API and retention."""

    text = DOC.read_text(encoding="utf-8")
    assert "exact-name Actions artifact ledger" in text
    assert "30-day" in text
    assert "REST API endpoints for GitHub Actions artifacts" in text
    assert "Store and share data with workflow artifacts" in text
