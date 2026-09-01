"""Regression contract for self-retiring Required OpenCode verdict polls."""

from pathlib import Path


WORKFLOW = Path(".github/workflows/opencode-review.yml")


def _fail_closed_step() -> str:
    """Return the production current-head verdict polling step."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    return workflow.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]


def _poll_loop() -> str:
    """Return only the long-running Reviews API polling loop."""
    step = _fail_closed_step()
    return step.split("          while :; do\n", 1)[1].split(
        "          done\n          if [ -z \"$verdict\" ]; then\n", 1
    )[0]


def test_poll_revalidates_live_pr_before_every_reviews_api_read() -> None:
    """An occupied runner must retire itself when its PR head stops being live."""
    loop = _poll_loop()
    live_lookup = (
        'live_poll_pr="$(gh api '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"'
    )
    reviews_lookup = (
        'reviews="$(gh api --paginate '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews")"'
    )

    assert live_lookup in loop
    assert 'live_poll_head="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'live_poll_draft="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'live_poll_state="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert (
        'if [ "${live_poll_head,,}" != "${HEAD_SHA,,}" ]; then' in loop
    )
    assert "superseded Required OpenCode Review poll" in loop
    assert 'if [ "$live_poll_state" = "closed" ]; then' in loop
    assert 'if [ "$live_poll_draft" = "true" ]; then' in loop
    assert reviews_lookup in loop
    assert loop.index(live_lookup) < loop.index(reviews_lookup)


def test_poll_live_state_revalidation_fails_closed_on_malformed_evidence() -> None:
    """Missing or malformed live-state evidence cannot turn a stale poll green."""
    loop = _poll_loop()
    assert (
        'if [ -z "$live_poll_head" ] || [ -z "$live_poll_draft" ] || '
        '[ -z "$live_poll_state" ]; then' in loop
    )
    assert "Could not validate live pull request state while polling" in loop
    assert (
        'if [ "$live_poll_state" != "open" ] && '
        '[ "$live_poll_state" != "closed" ]; then' in loop
    )


def test_self_retirement_does_not_replace_semantic_review_with_a_short_timeout() -> None:
    """Capacity hygiene must not impose an arbitrary review inference deadline."""
    target_job = WORKFLOW.read_text(encoding="utf-8").split(
        "  opencode-review-target:\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]
    assert "timeout-minutes:" not in target_job.split("    steps:\n", 1)[0]
    assert "while :; do" in target_job
    assert "sleep 30" in target_job
