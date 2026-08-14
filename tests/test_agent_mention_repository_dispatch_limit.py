"""Regression contract for GitHub repository-dispatch payload limits."""

from pathlib import Path

from scripts.ci import agent_mention_router as router


WORKFLOW = Path(".github/workflows/agent-mention-opencode-dispatch.yml")


def request() -> router.MentionRequest:
    """Return one complete review-only OpenCode request."""

    return router.MentionRequest(
        repository="ContextualWisdomLab/aFIPC",
        pull_request_number=212,
        pull_request_head_sha="a" * 40,
        pull_request_base_branch="master",
        comment_id=91,
        actor="maintainer",
        agents=("opencode-agent",),
        pull_request_base_sha="b" * 40,
    )


def test_opencode_dispatch_respects_ten_property_api_limit() -> None:
    """The first repository dispatch never exceeds GitHub's ten-key limit."""

    payload = router.opencode_payload(request())["client_payload"]

    assert len(payload) <= 10
    assert payload["review_contract"] == {
        "trigger_reviews": True,
        "review_dispatch_limit": "1",
        "enable_auto_merge": False,
        "update_branches": False,
        "merge_mode": "disabled",
    }
    assert payload["invocation"] == {
        "requested_agent": "opencode-agent",
        "agent_invocation_key": router.agent_invocation_key(
            request(), "opencode-agent"
        ),
        "requested_by": "maintainer",
        "source_comment_id": 91,
    }


def test_opencode_wrapper_unpacks_nested_claim_and_forwards_ten_keys() -> None:
    """The validated wrapper forwards only scheduler-required payload keys."""

    text = WORKFLOW.read_text(encoding="utf-8")

    assert "github.event.client_payload.review_contract.trigger_reviews" in text
    assert "github.event.client_payload.invocation.agent_invocation_key" in text
    forward = text.split(
        "Forward once to the authoritative review-only scheduler", maxsplit=1
    )[1]
    assert "requested_agent: $requested_agent" not in forward
    assert "agent_invocation_key: $agent_invocation_key" not in forward
    assert "requested_by: $requested_by" not in forward
    assert "source_comment_id: $source_comment_id" not in forward
