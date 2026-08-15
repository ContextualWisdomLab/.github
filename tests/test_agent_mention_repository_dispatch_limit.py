"""Regression contracts for GitHub repository-dispatch payload limits."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "scripts" / "ci" / "agent_mention_router.py"
OPENCODE_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-opencode-dispatch.yml"


def _load_router() -> ModuleType:
    """Load the mention router from the repository under test."""
    module_name = "agent_mention_repository_dispatch_limit_recurrence"
    spec = importlib.util.spec_from_file_location(module_name, ROUTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _request(router: ModuleType):
    """Return one complete OpenCode mention request."""
    return router.MentionRequest(
        repository="ContextualWisdomLab/example",
        pull_request_number=17,
        pull_request_head_sha="a" * 40,
        pull_request_base_branch="main",
        comment_id=91,
        actor="maintainer",
        agents=("opencode-agent",),
        pull_request_base_sha="b" * 40,
    )


def test_opencode_repository_dispatch_payload_has_at_most_ten_properties() -> None:
    """GitHub rejects repository-dispatch client payloads with over ten keys."""
    router = _load_router()
    payload = router.opencode_payload(_request(router))["client_payload"]

    assert len(payload) <= 10
    assert payload["review_policy"] == {
        "trigger_reviews": True,
        "review_dispatch_limit": "1",
        "enable_auto_merge": False,
        "update_branches": False,
        "merge_mode": "disabled",
    }


def test_opencode_wrapper_reads_nested_policy_and_forwards_ten_scheduler_fields() -> None:
    """The wrapper preserves policy binding and keeps its second dispatch within the limit."""
    workflow = OPENCODE_WORKFLOW.read_text(encoding="utf-8")

    for field in (
        "trigger_reviews",
        "review_dispatch_limit",
        "enable_auto_merge",
        "update_branches",
        "merge_mode",
    ):
        assert f"github.event.client_payload.review_policy.{field}" in workflow

    forward_block = workflow.split(
        "- name: Forward once to the authoritative review-only scheduler", 1
    )[1]
    for wrapper_only_field in (
        "requested_agent:",
        "agent_invocation_key:",
        "requested_by:",
        "source_comment_id:",
    ):
        assert wrapper_only_field not in forward_block

    expected_scheduler_fields = (
        "target_repository:",
        "pr_number:",
        "pr_head_sha:",
        "pr_base_sha:",
        "base_branch:",
        "trigger_reviews:",
        "review_dispatch_limit:",
        "enable_auto_merge:",
        "update_branches:",
        "merge_mode:",
    )
    for field in expected_scheduler_fields:
        assert field in forward_block
