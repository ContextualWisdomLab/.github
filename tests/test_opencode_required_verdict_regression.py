"""Regression coverage for the runtime required current-head OpenCode verdict gate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
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
    assert "Reject untrusted fork review resource consumption" in workflow
    assert "github.event.pull_request.head.repo.full_name" in workflow
    target_job = workflow.split("  opencode-review-target:\n", 1)[1]
    assert "timeout-minutes: 5" in target_job.split("    steps:\n", 1)[0]
    assert "for attempt in" not in workflow
    assert "opencode-review-wait-window-one" not in workflow
    assert "id-token: write" in target_job.split("    steps:\n", 1)[0]
    assert "steps.verdict.outputs.verdict == ''" in target_job
    assert 'event_type:"opencode-review"' in workflow
    assert 'sleep "$remaining_seconds"' not in workflow
    assert workflow.count("timeout 25 gh api --paginate") == 1
    assert workflow.count('if ! reviews="$(timeout 25 gh api') == 1
    assert workflow.count('reviews="[]"') == 1
    assert 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews"' in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "This required check is not a review and must not succeed" in workflow
    assert (
        "Review approval remains a separate current-head PR review requirement"
        not in workflow
    )


def test_formal_receipt_reruns_failed_required_job_without_runner_polling() -> None:
    """A formal receipt wakes the failed required run instead of polling for hours."""
    required = WORKFLOW.read_text(encoding="utf-8")
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    assert "for attempt in" not in required
    assert "rerun-failed-jobs" in dispatched
    assert "id: formal_review_receipt" in dispatched
    assert "steps.formal_review_receipt.outcome == 'success'" in dispatched
    assert 'select(.head_sha == $head)' in dispatched
    assert 'select(.event == "pull_request_target")' in dispatched
    assert 'select(.workflow_url | contains("/actions/required_workflows/"))' in dispatched
    assert 'startswith("Required OpenCode Review " + $repo + "#")' in dispatched


def test_formal_receipt_wakes_the_exact_head_failed_required_run(tmp_path: Path) -> None:
    """Execute the production wake script against a deterministic fake GitHub API."""
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    step = dispatched.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1]
    run_block = step.split("        run: |\n", 1)[1].split("\n\n      - name:", 1)[0]
    script = textwrap.dedent(run_block)
    calls = tmp_path / "calls"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>"$FAKE_CALLS"
if [[ "$*" == *"actions/runs?"* ]]; then
  printf '%s\\n' '{json.dumps({"workflow_runs": [{"id": 42, "head_sha": HEAD, "event": "pull_request_target", "name": "Required OpenCode Review ContextualWisdomLab/example#7@" + HEAD, "path": ".github/workflows/opencode-review.yml", "workflow_url": "https://api.github.com/repos/ContextualWisdomLab/example/actions/required_workflows/9", "status": "completed", "conclusion": "failure"}, {"id": 43, "head_sha": HEAD, "event": "pull_request_target", "name": "Required OpenCode Review ContextualWisdomLab/example#7@" + HEAD, "path": ".github/workflows/opencode-review.yml", "workflow_url": "https://api.github.com/repos/ContextualWisdomLab/example/actions/workflows/10", "status": "completed", "conclusion": "failure"}]})}'
  exit 0
fi
if [[ "$*" == *"actions/runs/42/rerun-failed-jobs"* ]]; then exit 0; fi
exit 1
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [shutil.which("bash") or "/bin/bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_CALLS": str(calls),
            "GH_REPOSITORY": "ContextualWisdomLab/example",
            "PR_HEAD_SHA": HEAD,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "actions/runs/42/rerun-failed-jobs" in calls.read_text(encoding="utf-8")
