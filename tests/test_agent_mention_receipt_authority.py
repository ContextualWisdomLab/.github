"""Contracts that keep target-repository receipt comments non-authoritative."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "ci"
sys.path.insert(0, str(SCRIPTS))


def test_receipt_looking_comments_never_suppress_a_trusted_request() -> None:
    """Only durable central exact-key workflow runs may suppress redispatch."""

    router = importlib.reload(importlib.import_module("agent_mention_router"))
    event = {
        "repository": {"full_name": "ContextualWisdomLab/inkspan"},
        "issue": {"number": 64, "pull_request": {"url": "https://example.test"}},
        "comment": {
            "id": 101,
            "body": "@opencode-agent",
            "author_association": "MEMBER",
            "user": {"login": "maintainer", "type": "User"},
        },
        "pull_request": {
            "state": "open",
            "head": {"sha": "a" * 40},
            "base": {"ref": "main"},
        },
        "conversation_comments": [
            {
                "body": "<!-- cwl-agent-mention-receipt:101 -->",
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            },
            {
                "body": "<!-- cwl-agent-mention-receipt:101 -->",
                "user": {"login": "rotated-installation-bot", "type": "Bot"},
            },
            {
                "body": "<!-- cwl-agent-mention-receipt:101 -->",
                "user": {"login": "attacker", "type": "User"},
            },
        ],
    }

    request = router.parse_event(event)
    assert request is not None
    assert request.comment_id == 101
    assert request.agents == ("opencode-agent",)


def test_sweep_does_not_use_target_receipts_as_dispatch_authority() -> None:
    """The organization sweep delegates suppression to the central run ledger."""

    source = (SCRIPTS / "agent_mention_sweep.py").read_text(encoding="utf-8")

    assert "processed_comment_ids" not in source
    assert "comment_id in processed" not in source
