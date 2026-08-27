"""Regression coverage for the required current-head OpenCode verdict gate."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ci import opencode_dispatch_status as dispatch_status


HEAD = "a" * 40


def review(*, state: str, commit_id: str = HEAD, body: str = "") -> dict[str, object]:
    """Build one Reviews API record from the OpenCode GitHub App."""
    return {
        "user": {"login": "opencode-agent[bot]"},
        "state": state,
        "commit_id": commit_id,
        "body": body,
    }


@pytest.mark.parametrize("state", ("APPROVED", "CHANGES_REQUESTED"))
def test_required_verdict_accepts_only_formal_current_head_states(state: str) -> None:
    """A substantive current-head formal state is passing evidence."""
    decide = getattr(dispatch_status, "decide_required_verdict_check", None)
    assert callable(decide), "required-verdict decision was removed"

    decision = decide(
        expected_head=HEAD,
        pull_request={"head": {"sha": HEAD}},
        reviews=[review(state=state)],
    )

    assert decision == {
        "state": "success",
        "description": f"Current-head OpenCode verdict: {state}.",
    }


@pytest.mark.parametrize(
    "reviews",
    (
        [],
        [review(state="COMMENTED")],
        [review(state="APPROVED", commit_id="b" * 40)],
        [review(state="APPROVED", body="deterministic fallback approval")],
    ),
)
def test_required_verdict_rejects_absent_placeholder_and_old_head_evidence(
    reviews: list[dict[str, object]],
) -> None:
    """Status-only, fallback, and predecessor evidence remain non-passing."""
    decide = getattr(dispatch_status, "decide_required_verdict_check", None)
    assert callable(decide), "required-verdict decision was removed"

    decision = decide(
        expected_head=HEAD,
        pull_request={"head": {"sha": HEAD}},
        reviews=reviews,
    )

    assert decision["state"] == "failure"
    assert "required check is not a review" in decision["description"]


def test_required_verdict_rejects_empty_target_stale_live_head_and_other_actor() -> None:
    """Malformed identity inputs and non-OpenCode reviews fail closed."""
    assert dispatch_status.current_head_opencode_verdict([], "") is None
    assert (
        dispatch_status.current_head_opencode_verdict(
            [
                {
                    "user": {"login": "coderabbitai[bot]"},
                    "state": "APPROVED",
                    "commit_id": HEAD,
                    "body": "",
                }
            ],
            HEAD,
        )
        is None
    )

    stale = dispatch_status.decide_required_verdict_check(
        expected_head=HEAD,
        pull_request={"head": {"sha": "c" * 40}},
        reviews=[review(state="APPROVED")],
    )

    assert stale["state"] == "failure"
    assert "target is stale" in stale["description"]


def test_required_workflow_cannot_succeed_with_an_echo_only_placeholder() -> None:
    """The required check must query Reviews API and fail without a verdict."""
    workflow = Path(".github/workflows/opencode-review.yml").read_text(encoding="utf-8")

    assert "pull-requests: read" in workflow
    assert "Fail closed without a current-head OpenCode verdict" in workflow
    assert 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews"' in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "This required check is not a review and must not succeed" in workflow
    assert (
        "Review approval remains a separate current-head PR review requirement"
        not in workflow
    )
