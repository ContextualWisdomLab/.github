"""Regression contract for self-retiring Required OpenCode verdict polls."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess


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


def _run_poll_loop(
    tmp_path: Path,
    *,
    head_sha: str,
    live_pr: dict[str, object],
    reviews: list[dict[str, object]] | None = None,
    fail_live_pr_attempts: int = 0,
    fail_review_attempts: int = 0,
    date_epochs: list[int] | None = None,
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    """Execute the production poll body against a deterministic fake ``gh``.

    ``date_epochs``, when given, stubs ``date`` to return each listed epoch
    in turn (clamped to the last entry once exhausted) instead of the real
    clock -- letting a test fast-forward past the real
    ``poll_deadline_epoch`` wall-clock deadline after a chosen number of
    genuinely-executed loop iterations, without ever sleeping for real time.
    """
    call_log = tmp_path / "gh-calls.log"
    live_fail_counter = tmp_path / "live-pr-failures"
    review_fail_counter = tmp_path / "review-failures"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$GH_CALL_LOG"
[ "${1:-}" = "api" ] || exit 90
shift
if [ "${1:-}" = "--paginate" ]; then
  count=0
  if [ -e "$GH_REVIEW_FAIL_COUNTER" ]; then
    count="$(cat "$GH_REVIEW_FAIL_COUNTER")"
  fi
  count=$((count + 1))
  printf '%s\\n' "$count" > "$GH_REVIEW_FAIL_COUNTER"
  if [ "$count" -le "${GH_FAIL_REVIEW_ATTEMPTS:-0}" ]; then
    exit 1
  fi
  printf '%s\\n' "$GH_REVIEWS"
else
  count=0
  if [ -e "$GH_LIVE_FAIL_COUNTER" ]; then
    count="$(cat "$GH_LIVE_FAIL_COUNTER")"
  fi
  count=$((count + 1))
  printf '%s\\n' "$count" > "$GH_LIVE_FAIL_COUNTER"
  if [ "$count" -le "${GH_FAIL_LIVE_PR_ATTEMPTS:-0}" ]; then
    exit 1
  fi
  printf '%s\\n' "$GH_LIVE_PR"
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_sleep = tmp_path / "sleep"
    fake_sleep.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_sleep.chmod(0o755)
    fake_timeout = tmp_path / "timeout"
    fake_timeout.write_text(
        "#!/bin/sh\nset -eu\nshift\nexec \"$@\"\n",
        encoding="utf-8",
    )
    fake_timeout.chmod(0o755)

    env_overrides: dict[str, str] = {}
    if date_epochs is not None:
        date_epochs_file = tmp_path / "date-epochs"
        date_epochs_file.write_text(
            "\n".join(str(epoch) for epoch in date_epochs) + "\n", encoding="utf-8"
        )
        date_counter = tmp_path / "date-calls"
        fake_date = tmp_path / "date"
        fake_date.write_text(
            """#!/bin/sh
set -eu
count=0
if [ -e "$FAKE_DATE_COUNTER" ]; then
  count="$(cat "$FAKE_DATE_COUNTER")"
fi
count=$((count + 1))
printf '%s\\n' "$count" > "$FAKE_DATE_COUNTER"
line="$(sed -n "${count}p" "$FAKE_DATE_EPOCHS")"
if [ -z "$line" ]; then
  line="$(tail -n1 "$FAKE_DATE_EPOCHS")"
fi
printf '%s\\n' "$line"
""",
            encoding="utf-8",
        )
        fake_date.chmod(0o755)
        env_overrides["FAKE_DATE_EPOCHS"] = str(date_epochs_file)
        env_overrides["FAKE_DATE_COUNTER"] = str(date_counter)

    script = "\n".join(
        (
            "set -euo pipefail",
            'verdict=""',
            'live_poll_failures=0',
            'review_poll_failures=0',
            'max_poll_transport_failures=3',
            'poll_interval_seconds=60',
            'poll_deadline_epoch=$(( $(date +%s) + 10800 ))',
            "while :; do",
            _poll_loop(),
            "done",
        )
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{tmp_path}{os.pathsep}{env.get('PATH', '')}",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "42",
            "HEAD_SHA": head_sha,
            "GH_CALL_LOG": str(call_log),
            "GH_FAIL_LIVE_PR_ATTEMPTS": str(fail_live_pr_attempts),
            "GH_FAIL_REVIEW_ATTEMPTS": str(fail_review_attempts),
            "GH_LIVE_FAIL_COUNTER": str(live_fail_counter),
            "GH_REVIEW_FAIL_COUNTER": str(review_fail_counter),
            "GH_LIVE_PR": json.dumps(live_pr),
            "GH_REVIEWS": json.dumps(reviews or []),
            **env_overrides,
        }
    )
    result = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        env=env,
        text=True,
    )
    calls = call_log.read_text(encoding="utf-8").splitlines()
    return result, calls


def test_poll_revalidates_live_pr_before_every_reviews_api_read() -> None:
    """An occupied runner must retire itself when its PR head stops being live."""
    loop = _poll_loop()
    live_lookup = (
        'live_poll_pr="$(timeout 30s gh api '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}")"'
    )
    reviews_lookup = (
        'reviews="$(timeout 30s gh api --paginate '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100")"'
    )

    assert live_lookup in loop
    assert 'live_poll_head="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'live_poll_draft="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'live_poll_state="$(printf \'%s\' "$live_poll_pr" | jq -r ' in loop
    assert 'if [ "${live_poll_head,,}" != "${HEAD_SHA,,}" ]; then' in loop
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


def test_poll_executes_superseded_head_retirement_before_reviews_read(
    tmp_path: Path,
) -> None:
    """A moved head exits non-passing before the Reviews API is consulted."""
    head_sha = "a" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": "b" * 40}, "draft": False, "state": "open"},
    )

    assert result.returncode == 1
    assert "retiring superseded Required OpenCode Review poll" in result.stdout
    assert calls == ["api repos/ContextualWisdomLab/example/pulls/42"]


def test_poll_executes_closed_pr_retirement_without_reviews_read(tmp_path: Path) -> None:
    """A closed current-head PR releases the occupied runner successfully."""
    head_sha = "c" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "closed"},
    )

    assert result.returncode == 0
    assert "PR closed while waiting" in result.stdout
    assert calls == ["api repos/ContextualWisdomLab/example/pulls/42"]


def test_poll_executes_live_state_read_before_current_head_review_read(
    tmp_path: Path,
) -> None:
    """A live head reads PR state first and then accepts only its current review."""
    head_sha = "d" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        reviews=[
            {
                "user": {"login": "opencode-agent[bot]"},
                "commit_id": head_sha,
                "state": "APPROVED",
                "body": "Source-backed current-head semantic review.",
            }
        ],
    )

    assert result.returncode == 0, result.stderr
    assert calls == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
    ]


def test_poll_retries_transient_live_state_failure_before_reviews_read(
    tmp_path: Path,
) -> None:
    """A transient live-state read failure retries without ending current authority."""
    head_sha = "e" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        reviews=[
            {
                "user": {"login": "opencode-agent[bot]"},
                "commit_id": head_sha,
                "state": "APPROVED",
                "body": "Source-backed current-head semantic review.",
            }
        ],
        fail_live_pr_attempts=1,
    )

    assert result.returncode == 0, result.stderr
    assert "Live pull request read failed while polling" in result.stdout
    assert calls == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
    ]


def test_poll_fails_closed_after_bounded_live_state_transport_failures(
    tmp_path: Path,
) -> None:
    """Repeated live-state failures release the runner without fabricated evidence."""
    head_sha = "f" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        fail_live_pr_attempts=3,
    )

    assert result.returncode == 1
    assert "Live pull request read failed 3 consecutive times" in result.stdout
    assert calls == ["api repos/ContextualWisdomLab/example/pulls/42"] * 3
    assert all("reviews" not in call for call in calls)


def test_poll_retries_transient_reviews_failure_after_revalidating_head(
    tmp_path: Path,
) -> None:
    """A Reviews API transport failure retries only after re-reading live PR state."""
    head_sha = "1" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        reviews=[
            {
                "user": {"login": "opencode-agent"},
                "commit_id": head_sha,
                "state": "APPROVED",
                "body": "Source-backed current-head semantic review.",
            }
        ],
        fail_review_attempts=1,
    )

    assert result.returncode == 0, result.stderr
    assert "Reviews API read failed while polling" in result.stdout
    assert calls == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
    ]


def test_poll_fails_closed_after_bounded_reviews_transport_failures(
    tmp_path: Path,
) -> None:
    """Repeated Reviews API failures stop after a finite number of attempts."""
    head_sha = "2" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        fail_review_attempts=3,
    )

    assert result.returncode == 1
    assert "Reviews API read failed 3 consecutive times" in result.stdout
    assert calls == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
    ] * 3


def test_self_retirement_does_not_replace_semantic_review_with_a_short_timeout() -> None:
    """Capacity hygiene must not impose an arbitrary review inference deadline."""
    target_job = WORKFLOW.read_text(encoding="utf-8").split(
        "  opencode-review-target:\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]
    assert "timeout-minutes:" not in target_job.split("    steps:\n", 1)[0]
    assert "while :; do" in target_job
    assert "poll_interval_seconds=60" in target_job
    assert 'sleep "$poll_interval_seconds"' in target_job


def test_poll_fails_closed_after_wall_clock_deadline_with_every_gh_call_succeeding(
    tmp_path: Path,
) -> None:
    """The zombie scenario: no transport failure ever occurs, yet no verdict posts.

    `max_poll_transport_failures` cannot catch this -- every `gh` call
    below succeeds -- so only a genuinely distinct wall-clock deadline
    (`poll_deadline_epoch`, computed once before the loop) can release the
    runner. A fake `date` fast-forwards past the real production 10800s
    (180-minute) bound only after two full, genuinely-executed fast
    iterations (proving the check is a real per-iteration wall-clock
    comparison, not a check that fires before any work happens), without
    this test ever sleeping for real time.
    """
    head_sha = "5" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        reviews=[],  # opencode-agent never posts a review on this head
        date_epochs=[1000, 1000, 1000, 999999999999],
    )

    assert result.returncode == 1
    assert (
        "::error::No current-head OpenCode verdict after 180 minutes of "
        "polling; failing closed and releasing the runner." in result.stdout
    )
    # Distinct diagnostic from the transport-failure path: nothing here failed.
    assert "consecutive times" not in result.stdout
    assert calls == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
    ]


def test_poll_wall_clock_deadline_does_not_interfere_with_a_fast_verdict(
    tmp_path: Path,
) -> None:
    """A verdict arriving on the first poll is unaffected by the new bound."""
    head_sha = "6" * 40
    result, calls = _run_poll_loop(
        tmp_path,
        head_sha=head_sha,
        live_pr={"head": {"sha": head_sha}, "draft": False, "state": "open"},
        reviews=[
            {
                "user": {"login": "opencode-agent[bot]"},
                "commit_id": head_sha,
                "state": "APPROVED",
                "body": "Source-backed current-head semantic review.",
            }
        ],
        date_epochs=[1000, 1000],  # baseline call, then one in-bounds iteration check
    )

    assert result.returncode == 0, result.stderr
    assert calls == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
    ]
    assert "No current-head OpenCode verdict after" not in result.stdout


def test_wall_clock_deadline_is_distinct_from_and_additional_to_transport_counter() -> None:
    """The new bound sits alongside, not in place of, the transport-failure counter.

    Pins the production shape so a future edit cannot quietly collapse the
    two into one, or drop the wall-clock bound back to unbounded: both
    `max_poll_transport_failures` (existing) and `poll_deadline_epoch`
    (computed once before the loop) must be present, and the wall-clock
    check must live inside the `while :; do` loop body -- not as a
    job-level `timeout-minutes:`, which would kill the runner mid-request
    instead of failing closed with a clear diagnostic.
    """
    target_job = WORKFLOW.read_text(encoding="utf-8").split(
        "  opencode-review-target:\n", 1
    )[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0]
    assert "max_poll_transport_failures=3" in target_job
    assert "poll_deadline_epoch=$(( $(date -u +%s) + 10800 ))" in target_job
    loop = _poll_loop()
    assert 'if [ "$(date -u +%s)" -ge "$poll_deadline_epoch" ]; then' in loop
    assert (
        "::error::No current-head OpenCode verdict after 180 minutes of "
        "polling; failing closed and releasing the runner." in loop
    )
    # The deadline check must precede this iteration's gh calls so an
    # already-expired deadline never spends another API request.
    assert loop.index('-ge "$poll_deadline_epoch"') < loop.index(
        'live_poll_pr="$(timeout 30s gh api'
    )
