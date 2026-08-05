"""Contracts that keep target-repository receipt comments non-authoritative."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "ci"
ROUTER_WORKFLOW = ROOT / ".github" / "workflows" / "agent-mention-router.yml"


def test_local_router_does_not_load_target_receipts_as_dispatch_authority() -> None:
    """The local path routes the source event without prior-comment receipts."""

    workflow = ROUTER_WORKFLOW.read_text(encoding="utf-8")
    local = workflow.split("\n  sweep-organization-agent-mentions:\n", 1)[0]

    assert "conversation_comments" not in local
    assert "/comments?per_page=100" not in local


def test_sweep_does_not_use_target_receipts_as_dispatch_authority() -> None:
    """The organization sweep delegates suppression to the central run ledger."""

    source = (SCRIPTS / "agent_mention_sweep.py").read_text(encoding="utf-8")

    assert "processed_comment_ids" not in source
    assert "comment_id in processed" not in source
    assert "/comments?per_page=100" not in source
