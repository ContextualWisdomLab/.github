"""Regression coverage for the runtime required current-head OpenCode verdict gate."""

from __future__ import annotations

import json
import os
import shutil
import stat
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


def test_required_workflow_reruns_on_draft_reconversion() -> None:
    """A ready PR converted back to draft must get a fresh required-workflow run.

    Without ``converted_to_draft`` in the trigger list, a PR that goes
    ready -> draft with no new commit keeps its previously failed
    ``opencode-review`` check forever: no event refires the job that could
    apply the draft exemption below.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert (
        "types: [opened, synchronize, reopened, ready_for_review, "
        "converted_to_draft, closed]"
    ) in workflow


def _extract_run_block(workflow_text: str, step_name: str) -> str:
    """Return the literal bash text of one workflow step's ``run: |`` block."""
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


def _render_step(script: str, *, event_action: str, draft: str) -> str:
    """Substitute the two inline ``${{ github.* }}`` expressions GitHub Actions
    would resolve before invoking bash, so the raw step body becomes directly
    executable outside of Actions."""
    rendered = script.replace("${{ github.event.action }}", event_action)
    rendered = rendered.replace("${{ github.event.pull_request.draft }}", draft)
    assert "${{" not in rendered, "unresolved GitHub Actions expression remains"
    return rendered


def _write_refusing_gh(bin_dir: Path) -> None:
    """Install a fake ``gh`` on PATH that fails loudly if it is ever invoked.

    Used to prove an early-exit branch never reaches the Reviews API call.
    """
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "echo 'unexpected gh invocation: the early-exit should have short-circuited' >&2\n"
        "exit 17\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)


def _write_reviews_gh(bin_dir: Path, reviews: list[dict[str, object]]) -> Path:
    """Install a fake ``gh`` on PATH that serves a fixed Reviews API page."""
    fake_gh = bin_dir / "gh"
    fixture = bin_dir / "reviews.json"
    fixture.write_text(json.dumps(reviews), encoding="utf-8")
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        f"cat {fixture}\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)
    return fake_gh


def _run_step(
    tmp_path: Path,
    *,
    event_action: str,
    draft: str,
    pr_number: str = "",
    head_sha: str = "",
    gh_fixture: str = "refuse",
    reviews: list[dict[str, object]] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the production step body with the given event shape.

    ``gh_fixture`` selects a fake ``gh`` on PATH: ``"refuse"`` fails loudly if
    invoked (proving an early exit never reaches the Reviews API call), and
    ``"reviews"`` serves ``reviews`` back from ``gh api``.
    """
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production step body")

    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = _render_step(
        _extract_run_block(workflow, STEP_NAME),
        event_action=event_action,
        draft=draft,
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if gh_fixture == "refuse":
        _write_refusing_gh(bin_dir)
    else:
        _write_reviews_gh(bin_dir, reviews or [])

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/example",
        "PR_NUMBER": pr_number,
        "HEAD_SHA": head_sha,
    }
    return subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def test_draft_pr_short_circuits_before_the_reviews_api_call(tmp_path: Path) -> None:
    """A draft PR passes without ever calling the Reviews API.

    The merge scheduler (``scripts/ci/pr_review_merge_scheduler.py``) never
    dispatches a review request for a draft PR, so this required check must
    not demand a verdict that was never going to be requested. ``PR_NUMBER``
    and ``HEAD_SHA`` are deliberately left unset here to prove the draft
    early-exit runs before the "missing PR number or head SHA" fail-closed
    check that follows it.
    """
    result = _run_step(
        tmp_path,
        event_action="synchronize",
        draft="true",
        gh_fixture="refuse",
    )
    assert result.returncode == 0, result.stderr
    assert "PR is a draft" in result.stdout


@pytest.mark.parametrize(
    "event_action", ("opened", "synchronize", "reopened", "converted_to_draft")
)
def test_draft_pr_short_circuits_on_every_non_closed_event_type(
    tmp_path: Path, event_action: str
) -> None:
    """The draft exemption applies uniformly across opened/synchronize/reopened."""
    result = _run_step(
        tmp_path,
        event_action=event_action,
        draft="true",
        gh_fixture="refuse",
    )
    assert result.returncode == 0, result.stderr
    assert "PR is a draft" in result.stdout


def test_ready_for_review_pr_still_requires_a_current_head_verdict(
    tmp_path: Path,
) -> None:
    """Once a PR is not a draft, the real gate still runs unchanged."""
    result = _run_step(
        tmp_path,
        event_action="ready_for_review",
        draft="false",
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="reviews",
        reviews=[review(state="APPROVED")],
    )
    assert result.returncode == 0, result.stderr
    assert "Current-head OpenCode verdict: APPROVED." in result.stdout


def test_non_draft_pr_without_a_verdict_still_fails_closed(tmp_path: Path) -> None:
    """A non-draft PR with no matching review still fails closed as before."""
    result = _run_step(
        tmp_path,
        event_action="synchronize",
        draft="false",
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="reviews",
        reviews=[],
    )
    assert result.returncode == 1
    assert "No APPROVED or CHANGES_REQUESTED from opencode-agent" in result.stdout


def test_closed_pr_short_circuits_before_the_draft_check(tmp_path: Path) -> None:
    """The pre-existing ``closed`` early-exit still takes precedence over draft."""
    result = _run_step(
        tmp_path,
        event_action="closed",
        draft="true",
        gh_fixture="refuse",
    )
    assert result.returncode == 0, result.stderr
    assert "PR closed; a current-head OpenCode verdict is not required." in result.stdout
    assert "PR is a draft" not in result.stdout
