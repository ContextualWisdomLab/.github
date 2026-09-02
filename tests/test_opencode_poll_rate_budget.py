"""Rate-budget regression for Required OpenCode review polling."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/opencode-review.yml")


def _poll_loop() -> str:
    """Return the long-running current-head verdict polling loop."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]
    return step.split("          while :; do\n", 1)[1].split(
        "          done\n          if [ -z \"$verdict\" ]; then\n", 1
    )[0]


def test_poll_retains_live_revalidation_but_bounds_rest_request_pressure() -> None:
    """Stale-head safety must not consume the repository token budget by design."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    loop = _poll_loop()

    assert "          poll_interval_seconds=60\n" in workflow
    live_lookup = (
        'live_poll_pr="$(timeout 30s gh api '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"'
    )
    reviews_lookup = (
        'reviews="$(timeout 30s gh api --paginate '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100")"'
    )
    assert live_lookup in loop
    assert reviews_lookup in loop
    assert loop.index(live_lookup) < loop.index(reviews_lookup)
    assert 'sleep "$poll_interval_seconds"' in loop
    assert "sleep 30" not in loop


def test_review_poll_uses_maximum_rest_page_size() -> None:
    """Review history pagination should minimize requests without dropping evidence."""
    loop = _poll_loop()
    assert "/reviews?per_page=100" in loop
    assert "gh api --paginate" in loop
