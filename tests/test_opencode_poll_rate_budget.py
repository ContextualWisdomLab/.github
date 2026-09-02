"""Request-budget regression for one-shot Required OpenCode verdict admission."""

from pathlib import Path

WORKFLOW = Path(".github/workflows/opencode-review.yml")

def _step() -> str:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]

def test_admission_uses_one_reviews_read_without_runner_polling() -> None:
    step = _step()
    assert step.count('gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"') == 1
    assert step.count('gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100"') == 1
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "sleep "):
        assert token not in step

def test_review_read_keeps_maximum_rest_page_size() -> None:
    step = _step()
    assert "/reviews?per_page=100" in step
    assert "gh api --paginate" in step
