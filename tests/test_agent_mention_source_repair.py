"""Explicit source commands must reach the canonical writer, not review-only dispatch."""
from __future__ import annotations

from scripts.ci import agent_mention_router as router
import pytest


def event(body: str) -> dict:
    """Build a same-repository human command with exact revision identities."""
    repo = "ContextualWisdomLab/bandscope"
    return {
        "repository": {"full_name": repo},
        "issue": {"number": 866, "pull_request": {"url": f"https://api.github.com/repos/{repo}/pulls/866"}},
        "comment": {"id": 9001, "body": body, "author_association": "MEMBER",
                    "user": {"login": "maintainer", "type": "User"}},
        "pull_request": {"state": "open",
                         "head": {"sha": "a" * 40, "ref": "fix/admission", "repo": {"full_name": repo}},
                         "base": {"sha": "b" * 40, "ref": "develop", "repo": {"full_name": repo}}},
    }


@pytest.mark.parametrize("verb", ["fix", "repair"])
def test_explicit_source_command_does_not_dispatch_review(verb: str) -> None:
    """The user's explicit write request must select the edit-capable worker."""
    request = router.parse_event(event(f"@opencode-agent {verb}\nFix regression."))
    assert request is not None
    payload = router.opencode_payload(request)
    assert payload["event_type"] == "pr-review-autofix"
    assert payload["client_payload"]["repair_mode"] == "mention"


def test_default_review_is_unchanged() -> None:
    """Normal review requests must never inherit write authority."""
    request = router.parse_event(event("@opencode-agent review"))
    assert router.opencode_payload(request)["event_type"] == "agent-mention-opencode"
