"""Regression contract for self-releasing Required OpenCode verdict admission."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/opencode-review.yml")


def _step() -> str:
    """Return only the one-shot exact-head verdict-admission step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]


def test_one_shot_revalidates_live_authority_before_review_evidence() -> None:
    """Live PR/head/draft/state authority precedes the complete Reviews read."""
    step = _step()
    live = 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"'
    reviews = 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews'
    assert live in step and reviews in step and step.index(live) < step.index(reviews)
    assert "Could not validate live pull request state before verdict admission" in step
    assert "PR is still a draft" in step
    assert "fresh required-review run will bind the current head" in step


def test_one_shot_has_no_repository_authored_wait_retry_or_transport_deadline() -> None:
    """No elapsed-time or fixed-attempt policy governs formal verdict admission."""
    step = _step()
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "max_poll_transport_failures", "sleep ", "timeout "):
        assert token not in step
