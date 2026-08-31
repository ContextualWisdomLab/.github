"""Regression coverage for the runtime required current-head OpenCode verdict gate."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


HEAD = "a" * 40
WORKFLOW = Path(".github/workflows/opencode-review.yml")
DISPATCH_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
STATUS_HELPER = Path("scripts/ci/opencode_dispatch_status.py")


def review(*, state: str, commit_id: str = HEAD, body: str = "") -> dict[str, object]:
    """Build one Reviews API record from the OpenCode GitHub App."""
    return {
        "user": {"login": "opencode-agent[bot]"},
        "state": state,
        "commit_id": commit_id,
        "body": body,
    }


def runtime_verdict(reviews: list[dict[str, object]], head_sha: str = HEAD) -> str:
    """Execute the jq program embedded in the required workflow."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production verdict filter")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = """jq -r -s --arg sha "$HEAD_SHA" '"""
    start = workflow.index(marker) + len(marker)
    end = workflow.index("\n          ')", start)
    result = subprocess.run(
        [jq, "-r", "-s", "--arg", "sha", head_sha, workflow[start:end]],
        input=json.dumps(reviews),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


@pytest.mark.parametrize("state", ("APPROVED", "CHANGES_REQUESTED"))
def test_runtime_required_verdict_accepts_only_formal_current_head_states(
    state: str,
) -> None:
    """A substantive current-head formal state is passing runtime evidence."""
    assert runtime_verdict([review(state=state)]) == state


@pytest.mark.parametrize(
    "reviews",
    (
        [],
        [review(state="COMMENTED")],
        [review(state="APPROVED", commit_id="b" * 40)],
        [review(state="APPROVED", body="deterministic fallback approval")],
    ),
)
def test_runtime_required_verdict_rejects_nonpassing_evidence(
    reviews: list[dict[str, object]],
) -> None:
    """Status-only, fallback, and predecessor evidence remain non-passing."""
    assert runtime_verdict(reviews) == ""


@pytest.mark.parametrize("state", ("APPROVED", "CHANGES_REQUESTED"))
def test_runtime_required_verdict_ignores_later_nonformal_current_head_comment(
    state: str,
) -> None:
    """A later COMMENTED receipt cannot mask the current-head formal verdict."""
    assert runtime_verdict(
        [review(state=state), review(state="COMMENTED", body="status-only follow-up")]
    ) == state


def test_runtime_required_verdict_rejects_other_actor() -> None:
    """A non-OpenCode formal review cannot satisfy the runtime filter."""
    human = review(state="APPROVED")
    human["user"] = {"login": "coderabbitai[bot]"}
    assert runtime_verdict([human]) == ""


def test_required_verdict_has_one_executable_owner() -> None:
    """Tests must execute the workflow gate, not a test-only Python mirror."""
    status_source = STATUS_HELPER.read_text(encoding="utf-8")
    assert "def current_head_opencode_verdict" not in status_source
    assert "def decide_required_verdict_check" not in status_source


def test_required_workflow_cannot_succeed_with_an_echo_only_placeholder() -> None:
    """The required check must query Reviews API and fail without a verdict."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "pull-requests: read" in workflow
    assert "Fail closed without a current-head OpenCode verdict" in workflow
    assert "Request current-head OpenCode review execution" in workflow
    assert "repos/ContextualWisdomLab/.github/dispatches" in workflow
    assert "exchange_github_app_token" in workflow
    target_job = workflow.split("  opencode-review-target:\n", 1)[1]
    job_header = target_job.split("    steps:\n", 1)[0]
    # Exact budget numbers (timeout-minutes, attempt count) are covered by
    # the arithmetic invariant tests below, which fail if either number
    # drifts out of a safe relationship instead of only if it changes at
    # all -- pin structure here, not the literals themselves.
    assert re.search(r"timeout-minutes: \d+", job_header)
    assert re.search(r"for attempt in \$\(seq 1 \d+\); do", target_job)
    assert "id-token: write" in job_header
    assert 'event_type:"merge-scheduler"' in workflow
    assert "trigger_reviews:true" in workflow
    assert "sleep 30" in target_job
    assert "enable_auto_merge:false" in workflow
    assert 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews"' in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "This required check is not a review and must not succeed" in workflow
    assert (
        "Review approval remains a separate current-head PR review requirement"
        not in workflow
    )


def _poller_numbers() -> dict[str, int]:
    """Parse the poller's own budget knobs straight out of the workflow text.

    Returns the loop's attempt count, sleep interval, per-call `gh api`
    timeout, and the enclosing job's own `timeout-minutes` -- all read from
    the live workflow, never hand-copied, so an edit to any of them is
    reflected here automatically instead of needing a matching test edit.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    target_job = workflow.split("  opencode-review-target:\n", 1)[1]
    job_header = target_job.split("    steps:\n", 1)[0]
    poll_step = target_job.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1]

    job_timeout_match = re.search(r"timeout-minutes: (\d+)", job_header)
    assert job_timeout_match, "enclosing job timeout-minutes not found"

    attempts_match = re.search(r"for attempt in \$\(seq 1 (\d+)\); do", poll_step)
    assert attempts_match, "poller loop attempt count not found"

    sleep_match = re.search(r"\n\s+sleep (\d+)\n\s*fi\n", poll_step)
    assert sleep_match, "poller loop sleep interval not found"

    per_call_timeout_match = re.search(
        r"timeout (\d+) "
        + re.escape(
            'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews"'
        ),
        poll_step,
    )
    assert per_call_timeout_match, "per-call gh api timeout wrapper not found"

    return {
        "job_timeout_minutes": int(job_timeout_match.group(1)),
        "attempts": int(attempts_match.group(1)),
        "sleep_seconds": int(sleep_match.group(1)),
        "per_call_timeout_seconds": int(per_call_timeout_match.group(1)),
    }


def _downstream_review_target_timeout_minutes() -> int:
    """Read opencode-review-dispatch.yml's own opencode-review-target budget.

    This is the job that actually executes the review and posts the verdict
    the poller above is waiting for; its timeout-minutes is the dominant
    term in how long a legitimate current-head verdict can take to appear.
    """
    dispatch_workflow = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    match = re.search(
        r"^  opencode-review-target:\n[\s\S]{0,4000}?^    timeout-minutes: (\d+)$",
        dispatch_workflow,
        re.MULTILINE,
    )
    assert match, "downstream opencode-review-target job timeout-minutes not found"
    return int(match.group(1))


def test_poll_budget_exceeds_downstream_review_job_budget_with_explicit_margin() -> None:
    """The poller must be able to outlast the downstream review job it awaits.

    Devin Review (PR #1507, 2026-08-31): the original loop's 639 sleeps x 30s
    = 319.5 minutes of polling patience was *less* than
    opencode-review-dispatch.yml's own opencode-review-target job's
    325-minute timeout-minutes budget -- before even counting the dispatch,
    queueing, and coverage-source-tree/coverage-evidence delay that job's
    needs: chain requires beforehand. This asserts the inequality directly
    from both workflows' live numbers (not hard-coded literals), so a future
    edit that shrinks the attempt count, shrinks the sleep interval, or
    grows the downstream budget without maintaining the relationship fails
    here instead of silently reintroducing the bug.
    """
    numbers = _poller_numbers()
    downstream_timeout_minutes = _downstream_review_target_timeout_minutes()

    poll_budget_seconds = (numbers["attempts"] - 1) * numbers["sleep_seconds"]
    downstream_budget_seconds = downstream_timeout_minutes * 60

    # Explicit safety/cleanup margin (Devin Review's phrase): require the
    # poller to clear the downstream job's own budget by a real, deliberate
    # amount, not by happenstance rounding.
    explicit_margin_seconds = 5 * 60

    assert poll_budget_seconds >= downstream_budget_seconds + explicit_margin_seconds, (
        f"poll budget {poll_budget_seconds}s ({poll_budget_seconds / 60}m) does "
        f"not clear the downstream opencode-review-target job's "
        f"{downstream_budget_seconds}s ({downstream_timeout_minutes}m) budget "
        f"plus a {explicit_margin_seconds}s margin"
    )


def test_enclosing_job_timeout_has_headroom_above_the_poll_budget() -> None:
    """The enclosing job must not die of its own timeout before the loop gives up.

    CodeRabbit finding (PR #1507, 2026-08-31): the loop's `sleep 30` calls are
    not the only time the job spends -- the dispatch step and up to
    `attempts` sequential `gh api --paginate` calls also consume wall-clock
    time that was previously unbudgeted. Each call is now wrapped in an
    explicit `timeout` so a single hung or heavily-paginated call cannot
    silently consume unbounded time; this test asserts the job's own
    timeout-minutes leaves enough slack above the pure-sleep budget to
    absorb that per-call cap several times over plus fixed overhead, so the
    loop's own "::error::No APPROVED or CHANGES_REQUESTED" failure fires
    before GitHub's job-level timeout kills the job mid-poll.
    """
    numbers = _poller_numbers()

    # GitHub-hosted runners hard-cap every job's wall-clock at 6 hours (360
    # minutes) regardless of timeout-minutes
    # (docs.github.com/en/actions/reference/limits); a configured value above
    # that is silently truncated by the platform, which would make
    # timeout-minutes misleading documentation rather than an honored
    # setting.
    github_hosted_job_wall_clock_cap_minutes = 360
    assert numbers["job_timeout_minutes"] <= github_hosted_job_wall_clock_cap_minutes

    poll_budget_seconds = (numbers["attempts"] - 1) * numbers["sleep_seconds"]
    job_budget_seconds = numbers["job_timeout_minutes"] * 60
    slack_seconds = job_budget_seconds - poll_budget_seconds

    # The slack must comfortably absorb several calls hitting the per-call
    # cap (dispatch step + occasional slow/paginated gh api calls) and still
    # leave the loop's own clean failure path room to run and the job room
    # to shut down, rather than being killed mid-call by GitHub itself.
    assert slack_seconds >= numbers["per_call_timeout_seconds"] * 5, (
        f"job timeout only leaves {slack_seconds}s of slack above the "
        f"{poll_budget_seconds}s poll budget; need room for several "
        f"{numbers['per_call_timeout_seconds']}s-capped gh api calls plus "
        "dispatch/runner overhead"
    )
    minimum_slack_seconds = 20 * 60
    assert slack_seconds >= minimum_slack_seconds, (
        f"job timeout only leaves {slack_seconds}s of slack above the "
        f"poll budget; need at least {minimum_slack_seconds}s for the "
        "dispatch step, cumulative gh api latency, and runner/shutdown "
        "overhead"
    )


def test_poller_gh_api_call_has_an_explicit_per_call_timeout() -> None:
    """A single hung or heavily-paginated call must not eat unbudgeted time.

    CodeRabbit finding (PR #1507, 2026-08-31): the loop budgeted `sleep 30`
    between attempts but nothing bounded the `gh api --paginate` call
    itself, so one slow call (or a PR with enough reviews to paginate across
    many pages) could silently consume time that was not accounted for
    anywhere. The call must be wrapped in `timeout`, strictly under the
    sleep interval (so a capped call still leaves room for its sleep), and a
    failed/timed-out call must degrade to "no verdict yet" rather than
    crashing the step under `set -euo pipefail`.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    target_job = workflow.split("  opencode-review-target:\n", 1)[1]
    poll_step = target_job.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1]

    numbers = _poller_numbers()
    assert 0 < numbers["per_call_timeout_seconds"] < numbers["sleep_seconds"]
    assert (
        'if ! reviews="$(timeout '
        f'{numbers["per_call_timeout_seconds"]} gh api --paginate '
        '"repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews")"; then'
        in poll_step
    )
    assert 'reviews="[]"' in poll_step
