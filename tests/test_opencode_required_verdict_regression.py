"""Regression coverage for the runtime required current-head OpenCode verdict gate."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


HEAD = "a" * 40
WORKFLOW = Path(".github/workflows/opencode-review.yml")
STATUS_HELPER = Path("scripts/ci/opencode_dispatch_status.py")
STEP_NAME = "Fail closed without a current-head OpenCode verdict"


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
    assert 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews"' in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "This required check is not a review and must not succeed" in workflow
    assert (
        "Review approval remains a separate current-head PR review requirement"
        not in workflow
    )


def _extract_run_block(workflow_text: str, step_name: str) -> str:
    """Return the raw shell body of one named workflow step."""
    lines = workflow_text.splitlines()
    step_index = next(
        index for index, line in enumerate(lines) if line.strip() == f"- name: {step_name}"
    )
    run_index = next(
        index
        for index in range(step_index + 1, len(lines))
        if lines[index].strip() == "run: |"
    )
    run_indent = len(lines[run_index]) - len(lines[run_index].lstrip())
    block_lines = []
    for line in lines[run_index + 1 :]:
        if line.strip() and len(line) - len(line.lstrip()) <= run_indent:
            break
        block_lines.append(line[run_indent + 2 :] if len(line) >= run_indent + 2 else "")
    return "\n".join(block_lines) + "\n"


def _rendered_verdict_script(*, event_name: str, event_action: str = "") -> str:
    """Return the verdict step's shell body with its inline expressions rendered.

    GitHub Actions substitutes ``${{ ... }}`` expressions directly into the
    script text before any shell ever runs it, so exercising this step
    outside Actions requires performing that same literal substitution --
    ``PR_NUMBER``/``HEAD_SHA``/``TARGET_REPOSITORY`` remain real environment
    variables (set by the step's own ``env:`` block, not text substitution)
    and are supplied by the caller through the subprocess environment
    instead.
    """
    script = _extract_run_block(WORKFLOW.read_text(encoding="utf-8"), STEP_NAME)
    return script.replace("${{ github.event.action }}", event_action).replace(
        "${{ github.event_name }}", event_name
    )


def test_workflow_run_trigger_gives_a_same_repository_second_chance() -> None:
    """opencode-review.yml re-enters after "Required PR Review Merge Scheduler" completes.

    See ContextualWisdomLab/.github#1485: opencode-review-dispatch.yml (which
    posts the real review) always runs inside ContextualWisdomLab/.github and
    is not distributed by the required-workflow ruleset into sibling
    repositories, so workflow_run -- which cannot cross repositories -- could
    never observe its completion from a sibling repository's copy of this
    file. "Required PR Review Merge Scheduler" IS ruleset-distributed into
    every target repository and reacts to pull_request_review immediately
    when the real review posts, so it is the source workflow this file
    listens to instead.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    on_block = workflow.split("concurrency:", 1)[0]
    assert "workflow_run:" in on_block
    assert 'workflows: ["Required PR Review Merge Scheduler"]' in on_block
    assert "types: [completed]" in on_block
    assert '"OpenCode Review Dispatch"' not in on_block
    assert "ContextualWisdomLab/.github#1485" in on_block
    assert (
        "github.event.pull_request.number || github.event.workflow_run.pull_requests[0].number"
        in workflow
    )


def test_required_workflow_bootstrap_is_pull_request_target_only() -> None:
    """The Pingora bootstrap chain stays scoped to the pull_request_target path.

    A workflow_run second-chance re-entry has no ``github.event.pull_request``
    context for the Pingora policy inputs, so the bootstrap chain
    (required-workflow-bootstrap, coverage-source-tree, coverage-evidence)
    must cascade-skip for that event rather than run with wrong inputs.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    bootstrap_job = workflow.split("required-workflow-bootstrap:\n", 1)[1].split(
        "\n  coverage-source-tree:", 1
    )[0]
    assert "if: github.event_name == 'pull_request_target'" in bootstrap_job
    # Regression guard against the redundant ${{ }}-wrapped style this repo
    # avoids for job-level `if:` conditions.
    assert "if: ${{ github.event_name == 'pull_request_target' }}" not in workflow


def test_opencode_review_target_permits_workflow_run_reentry() -> None:
    """The required check job runs standalone for a non-cancelled workflow_run event."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    target_job = workflow.split("\n  opencode-review-target:\n", 1)[1]
    condition = target_job.split("permissions:", 1)[0]
    assert "always()" in condition
    assert "github.event.workflow_run.conclusion != 'cancelled'" in condition
    assert "github.event_name == 'workflow_run'" in condition
    assert "needs.coverage-evidence.result == 'success'" in condition


def test_verdict_step_skips_cleanly_when_workflow_run_has_no_pull_request(
    tmp_path: Path,
) -> None:
    """A scheduler completion with no associated PR exits 0 without calling gh.

    This covers the periodic-sweep-triggered "Required PR Review Merge
    Scheduler" completions, whose workflow_run event carries no
    ``pull_requests`` entry -- there is nothing to verify, and it must not be
    treated as the original "missing PR number" fail-closed case.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to execute the production verdict step")
    script = _rendered_verdict_script(event_name="workflow_run")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\necho 'gh must not be invoked here' >&2\nexit 1\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GH_TOKEN": "token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/contextual-orchestrator",
        "PR_NUMBER": "",
        "HEAD_SHA": "",
    }
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "No pull request is associated with this workflow_run event" in result.stdout


def test_verdict_step_workflow_run_reentry_passes_once_the_real_review_landed(
    tmp_path: Path,
) -> None:
    """A workflow_run re-entry succeeds once the async dispatch posted a real verdict.

    This is the actual race fix: opencode-review-dispatch.yml posts the real
    opencode-agent review well after the original pull_request_target run of
    this job already failed; this re-entry, triggered once "Required PR
    Review Merge Scheduler" reacts to that same review landing
    (pull_request_review: submitted), re-evaluates the identical Reviews API
    check and now finds it.
    """
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production verdict step")
    script = _rendered_verdict_script(event_name="workflow_run")
    reviews_json = json.dumps([review(state="APPROVED")])
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
test "$1" = api
test "$2" = --paginate
test "$3" = "repos/ContextualWisdomLab/contextual-orchestrator/pulls/955/reviews"
printf '%s\\n' '{reviews_json}'
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GH_TOKEN": "token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/contextual-orchestrator",
        "PR_NUMBER": "955",
        "HEAD_SHA": HEAD,
    }
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, env=env, check=False
    )
    assert result.returncode == 0, result.stderr
    assert "Current-head OpenCode verdict: APPROVED." in result.stdout


def test_verdict_step_pull_request_target_still_fails_closed_without_a_review(
    tmp_path: Path,
) -> None:
    """The original synchronous pull_request_target race behavior is unchanged.

    Regression guard: adding the workflow_run re-entry must not weaken the
    original required check's fail-closed behavior on its own first,
    synchronous evaluation.
    """
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production verdict step")
    script = _rendered_verdict_script(event_name="pull_request_target")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' '[]'\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "GH_TOKEN": "token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/.github",
        "PR_NUMBER": "1492",
        "HEAD_SHA": HEAD,
    }
    result = subprocess.run(
        ["bash"], input=script, text=True, capture_output=True, env=env, check=False
    )
    assert result.returncode == 1
    assert (
        "No APPROVED or CHANGES_REQUESTED from opencode-agent on the current head"
        in result.stdout
    )
