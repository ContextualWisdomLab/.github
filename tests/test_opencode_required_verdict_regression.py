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
    assert "timeout-minutes: 340" in target_job.split("    steps:\n", 1)[0]
    assert "id-token: write" in target_job.split("    steps:\n", 1)[0]
    assert 'event_type:"merge-scheduler"' in workflow
    assert "trigger_reviews:true" in workflow
    assert "for attempt in $(seq 1 660)" in target_job
    assert "sleep 30" in target_job
    assert "enable_auto_merge:false" in workflow
    assert 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews"' in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "This required check is not a review and must not succeed" in workflow
    assert (
        "Review approval remains a separate current-head PR review requirement"
        not in workflow
    )


def test_verdict_poll_budget_covers_the_dispatched_review_jobs_own_ceiling() -> None:
    """The poll must outlast the worker job it is waiting on.

    ContextualWisdomLab/.github#1500, #1506 and contextual-orchestrator#968,
    #946 all showed the same pattern: the "Request current-head OpenCode
    review execution" dispatch step always succeeded, but the poll loop below
    it always gave up (fail-closed, "No APPROVED or CHANGES_REQUESTED...")
    before opencode-review-dispatch.yml's own opencode-review-target job —
    whose model-pool step alone is budgeted 205 minutes for
    contextual-orchestrator sidecar preflight/escalation across its
    free-tier candidate pool, per
    test_opencode_job_timeout_contains_full_sequential_review_budget — ever
    had a chance to post a verdict. A poll budget shorter than the dispatched
    job's own declared ceiling makes a legitimate slow-but-successful review
    indistinguishable from a genuinely broken dispatch. Guard both the outer
    job timeout and the actual poll wall-clock budget against regressing
    below that ceiling again.
    """
    poll_workflow = WORKFLOW.read_text(encoding="utf-8")
    dispatch_workflow = DISPATCH_WORKFLOW.read_text(encoding="utf-8")

    target_job = poll_workflow.split("  opencode-review-target:\n", 1)[1]
    job_section = target_job.split("    steps:\n", 1)[0]
    poll_job_timeout_match = re.search(r"timeout-minutes: (\d+)", job_section)
    assert poll_job_timeout_match, "poll job is missing a timeout-minutes value"
    poll_job_timeout = int(poll_job_timeout_match.group(1))

    attempts_match = re.search(r"for attempt in \$\(seq 1 (\d+)\); do", target_job)
    sleep_match = re.search(r"\n\s+sleep (\d+)\n", target_job)
    assert attempts_match and sleep_match, "poll loop shape changed unexpectedly"
    poll_wait_minutes = (int(attempts_match.group(1)) - 1) * int(sleep_match.group(1)) / 60

    dispatch_job_timeout_match = re.search(
        r"^  opencode-review-target:\n[\s\S]{0,4000}?^    timeout-minutes: (\d+)$",
        dispatch_workflow,
        re.MULTILINE,
    )
    assert dispatch_job_timeout_match, "dispatch job timeout contract moved"
    dispatch_job_timeout = int(dispatch_job_timeout_match.group(1))

    assert poll_job_timeout >= dispatch_job_timeout, (
        "opencode-review-target's poll job can be killed by its own "
        f"timeout-minutes ({poll_job_timeout}) before the dispatched "
        "opencode-review-dispatch.yml job's own ceiling "
        f"({dispatch_job_timeout}) is reached."
    )
    assert poll_wait_minutes >= dispatch_job_timeout, (
        f"The verdict poll loop gives up after {poll_wait_minutes:.0f}m, "
        f"sooner than the dispatched review job is allowed to run "
        f"({dispatch_job_timeout}m)."
    )
