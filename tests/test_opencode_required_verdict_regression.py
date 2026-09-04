"""Regression coverage for the runtime required current-head OpenCode verdict gate."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


HEAD = "a" * 40
WORKFLOW = Path(".github/workflows/opencode-review.yml")
DISPATCH_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
STATUS_HELPER = Path("scripts/ci/opencode_dispatch_status.py")
RECEIPT_HELPER = Path("scripts/ci/opencode_review_receipt_gate.py")


def request_review_script() -> str:
    """Extract the production scheduler-wake run block."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Request current-head OpenCode review execution\n", 1
    )[1]
    block = step.split("        run: |\n", 1)[1].split(
        "\n      - name: Fail closed", 1
    )[0]
    return textwrap.dedent(block)


def fail_closed_script() -> str:
    """Extract the production "Fail closed without a current-head OpenCode verdict" run block."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def admission_script() -> str:
    """Extract the exact-head admission shell that precedes concurrency."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split("      - name: Admit only the exact live OpenCode head\n", 1)[1]
    return textwrap.dedent(step.split("        run: |\n", 1)[1].split("\n\n  coverage-source-tree:", 1)[0])


def test_stale_opencode_event_never_reaches_review_concurrency(tmp_path: Path) -> None:
    """A delayed old synchronize event is retired by live-head admission."""
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nprintf '%s' '{\"head\":{\"sha\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\"},\"state\":\"open\"}'\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    output = tmp_path / "github-output"
    result = subprocess.run(
        [shutil.which("bash") or "/bin/bash", "-c", admission_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "GH_TOKEN": "synthetic-token",
            "GITHUB_OUTPUT": str(output),
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "7",
            "EXPECTED_HEAD_SHA": HEAD,
            "EXPECTED_ACTION": "synchronize",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8").splitlines() == ["admitted=false"]
    assert "retired a stale event" in result.stdout


def test_opencode_dispatch_uses_the_same_target_repo_pr_group() -> None:
    """PR and repository_dispatch review jobs compute the same group text."""
    required = WORKFLOW.read_text(encoding="utf-8")
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    assert "opencode-review-${{" in required
    assert "opencode-review-${{" in dispatched
    assert "needs.validate-pr-metadata.outputs.target_repository" in dispatched
    assert "needs.validate-pr-metadata.outputs.pr_number || github.run_id" in dispatched
    assert "cancel-in-progress: true" in dispatched
    assert dispatched.index("validate-pr-metadata:") < dispatched.index("    concurrency:")


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


def cleanup_candidate_run_ids(
    runs: list[dict[str, object]],
    *,
    pr_number: str = "1437",
    head_sha: str = HEAD,
    repository: str = "ContextualWisdomLab/example",
    current_run_id: str = "999",
) -> list[str]:
    """Execute the jq program embedded in the superseded-run cleanup job."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production cleanup filter")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    marker = (
        'jq -r --arg pr "$TARGET_PR_NUMBER" --arg head_sha "$TARGET_PR_HEAD_SHA" \\\n'
        '              --arg repo "$TARGET_REPOSITORY" --arg current "$CURRENT_RUN_ID" \''
    )
    start = workflow.index(marker) + len(marker)
    end = workflow.index("\n              ' <<<\"$runs_json\")", start)
    result = subprocess.run(
        [
            jq,
            "-r",
            "--arg",
            "pr",
            pr_number,
            "--arg",
            "head_sha",
            head_sha,
            "--arg",
            "repo",
            repository,
            "--arg",
            "current",
            current_run_id,
            workflow[start:end],
        ],
        input=json.dumps({"workflow_runs": runs}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return [line for line in result.stdout.splitlines() if line]


def _cleanup_run(
    *,
    run_id: int,
    head_sha: str = HEAD,
    name: str = "Required OpenCode Review",
    event: str = "pull_request_target",
    display_title: str | None = None,
    pr_number: int = 1437,
) -> dict[str, object]:
    """Build one synthetic workflow-run record for the cleanup filter."""
    title = (
        display_title
        if display_title is not None
        else f"Required OpenCode Review ContextualWisdomLab/example#{pr_number}@{head_sha}"
    )
    return {
        "id": run_id,
        "name": name,
        "event": event,
        "display_title": title,
        "pull_requests": [{"number": pr_number, "head": {"sha": head_sha}}],
    }


def test_cleanup_selects_a_superseded_older_head_run() -> None:
    """An older run for a different, no-longer-live head is selected."""
    stale = _cleanup_run(run_id=1, head_sha="b" * 40)
    assert cleanup_candidate_run_ids([stale], current_run_id="999") == ["1"]


def test_cleanup_excludes_the_current_live_head_run() -> None:
    """A run already on the live exact head is never selected."""
    current_head_run = _cleanup_run(run_id=1, head_sha=HEAD)
    assert cleanup_candidate_run_ids([current_head_run], current_run_id="999") == []


def test_cleanup_excludes_the_currently_executing_run_itself() -> None:
    """The cleanup job's own run is never a cancellation candidate."""
    self_run = _cleanup_run(run_id=999, head_sha="b" * 40)
    assert cleanup_candidate_run_ids([self_run], current_run_id="999") == []


def test_cleanup_excludes_a_different_pull_request() -> None:
    """A stale-head run for an unrelated PR is left untouched."""
    other_pr = _cleanup_run(run_id=1, head_sha="b" * 40, pr_number=9999)
    assert cleanup_candidate_run_ids([other_pr], current_run_id="999") == []


def test_cleanup_excludes_a_differently_named_or_triggered_run() -> None:
    """A same-PR run for another workflow or trigger is left untouched."""
    other_workflow = _cleanup_run(run_id=1, head_sha="b" * 40, name="Strix Security Scan")
    other_event = _cleanup_run(run_id=2, head_sha="b" * 40, event="workflow_dispatch")
    assert (
        cleanup_candidate_run_ids([other_workflow, other_event], current_run_id="999")
        == []
    )


def test_cleanup_matches_by_pull_requests_metadata_when_title_omits_the_suffix() -> None:
    """A run whose display_title never rendered the head suffix still resolves."""
    metadata_only = _cleanup_run(
        run_id=1, head_sha="b" * 40, display_title="Required OpenCode Review"
    )
    assert cleanup_candidate_run_ids([metadata_only], current_run_id="999") == ["1"]


def test_cleanup_job_is_scoped_to_synchronize_events_with_actions_write() -> None:
    """The cleanup job only fires on synchronize and can cancel runs."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    job = workflow.split("  cancel-superseded-opencode-review-runs:\n", 1)[1]
    assert (
        "if: github.event_name == 'pull_request_target' && "
        "github.event.action == 'synchronize'"
    ) in job
    assert "actions: write" in job.split("steps:", 1)[0]


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
    assert "timeout-minutes:" not in target_job.split("    steps:\n", 1)[0]
    assert "id-token: write" in target_job.split("    steps:\n", 1)[0]
    assert 'event_type:"opencode-review"' in workflow
    assert "required_run_id:$required_run_id" in workflow
    dispatch_step = target_job.split(
        "      - name: Request current-head OpenCode review execution", 1
    )[1].split("      - name: Fail closed", 1)[0]
    assert "scripts/ci/opencode_review_receipt_gate.py" in dispatch_step
    assert "github.workflow_sha" in dispatch_step
    assert "evaluate_receipts" in dispatch_step
    assert dispatch_step.index("evaluate_receipts") < dispatch_step.index(
        "exchange_github_app_token"
    )
    assert "Current-head substantive OpenCode verdict already exists; scheduler wake skipped." in dispatch_step
    assert "while :; do" not in target_job
    assert "poll_interval_seconds" not in target_job
    assert "180 minutes of polling" not in target_job
    assert 'gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews?per_page=100"' in workflow
    assert "github.event.pull_request.head.sha" in workflow
    assert "will rerun this failed job" in workflow
    assert (
        "Review approval remains a separate current-head PR review requirement"
        not in workflow
    )


def _write_live_pr_then_refusing_gh(bin_dir: Path) -> None:
    """Serve the authoritative live PR lookup, then reject further GitHub I/O."""
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/pulls/1437\" ]]; then\n"
        "  printf '%s' \"$LIVE_PR_JSON\"\n"
        "  exit 0\n"
        "fi\n"
        "echo 'unexpected gh invocation after live-state validation' >&2\n"
        "exit 17\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | 0o111)


def _run_fail_closed_step(
    tmp_path: Path,
    *,
    pr_action: str = "",
    pr_draft: str = "false",
    pr_number: str = "1437",
    head_sha: str = HEAD,
    live_head_sha: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the "Fail closed without a current-head OpenCode verdict" step body.

    A fake ``gh`` fails loudly if a closed or draft early exit reaches the
    single Reviews API request.

    ``live_head_sha`` defaults to ``head_sha`` (an exact-head snapshot) but
    can be set independently to simulate a push landing between the event
    snapshot (``HEAD_SHA``) and this step's own live re-fetch.
    """
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production step body")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_live_pr_then_refusing_gh(bin_dir)
    return subprocess.run(
        [bash, "-c", fail_closed_script()],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "fake-token",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": pr_number,
            "HEAD_SHA": head_sha,
            "PR_ACTION": pr_action,
            "PR_DRAFT": pr_draft,
            "LIVE_PR_JSON": json.dumps(
                {
                    "draft": pr_draft.lower() == "true",
                    "head": {"sha": live_head_sha if live_head_sha is not None else head_sha},
                    "state": "open",
                }
            ),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_fail_closed_step_exempts_a_draft_pr_before_review_lookup(tmp_path: Path) -> None:
    """A draft PR's required check passes without reading Reviews API.

    `#1546` added `PR_DRAFT` to the dispatch step's receipt-gate check
    (`evaluate_receipts(..., is_draft=...)`), but that only narrows which
    reviews the gate accepts -- it never exempts a draft PR from needing one,
    and the scheduler's own draft path
    (`scripts/ci/pr_review_merge_scheduler.py`'s `inspect_pr`) skips
    dispatching a review for an ordinary draft entirely (no
    `@opencode-agent` mention).
    """
    result = _run_fail_closed_step(tmp_path, pr_action="synchronize", pr_draft="true")
    assert result.returncode == 0, result.stderr
    assert "PR is still a draft on the live exact head; a current-head OpenCode verdict is not required" in result.stdout


def _run_request_review_step(
    tmp_path: Path,
    *,
    pr_draft: str = "false",
    live_head_sha: str | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the "Request current-head OpenCode review execution" step body.

    A fake ``gh`` that fails loudly is installed on ``PATH`` so a draft
    early exit that reaches any API call at all -- fetching the receipt-gate
    helper source, or the Reviews API it wraps -- fails the test
    immediately.

    ``live_head_sha`` defaults to the fixed ``HEAD_SHA`` event snapshot but
    can be set independently to simulate a push landing between the event
    snapshot and this step's own live re-fetch.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to execute the production step body")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_live_pr_then_refusing_gh(bin_dir)
    return subprocess.run(
        [bash, "-c", request_review_script()],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "fake-token",
            "OIDC_AUDIENCE": "opencode-github-action",
            "OPENCODE_API_BASE_URL": "https://api.opencode.ai",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "1437",
            "HEAD_SHA": HEAD,
            "PR_DRAFT": pr_draft,
            "BASE_BRANCH": "main",
            "WORKFLOW_SHA": "c" * 40,
            "LIVE_PR_JSON": json.dumps(
                {
                    "draft": pr_draft.lower() == "true",
                    "head": {"sha": live_head_sha if live_head_sha is not None else HEAD},
                    "state": "open",
                }
            ),
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_request_review_step_exempts_a_pr_converted_to_draft_before_any_api_call(
    tmp_path: Path,
) -> None:
    """A PR converted to draft must not dispatch a new review request either.

    Devin Review on `#1568` found that `converted_to_draft` firing this
    workflow only fixed the "Fail closed" step's own poll -- the sibling
    "Request current-head OpenCode review execution" step (which runs first)
    had no draft exemption at all, so it still fetched the receipt-gate
    helper source and queried the Reviews API, and could reach OIDC token
    exchange and a `repository_dispatch` scheduler wake, before the "Fail
    closed" step's exemption ever ran. This proves the request step now performs only the authoritative live-state lookup, then
    exits before helper-source, review, token, or dispatch API calls when
    `PR_DRAFT` is `"true"` (the value GitHub sends for `converted_to_draft`),
    while `ready_for_review` and explicit draft-review dispatch paths
    elsewhere (`pr_review_merge_scheduler.py`'s own draft handling) are
    untouched by this step-body change.
    """
    result = _run_request_review_step(tmp_path, pr_draft="true")
    assert result.returncode == 0, result.stderr
    assert "PR is still a draft on the live exact head; a current-head OpenCode review is not requested" in result.stdout


def test_request_review_step_still_dispatches_for_a_non_draft_pr(
    tmp_path: Path,
) -> None:
    """A non-draft PR must still reach the receipt-gate helper fetch."""
    result = _run_request_review_step(tmp_path, pr_draft="false")
    assert result.returncode == 17, result.stderr
    assert "unexpected gh invocation after live-state validation" in result.stderr


def test_request_review_step_exempts_a_draft_pr_whose_live_head_has_moved(
    tmp_path: Path,
) -> None:
    """Reproduces the production failure this fix targets, verbatim.

    contextual-orchestrator PR #1000 was -- and remained -- a draft the
    whole time, but a push landed between the `pull_request_target` event
    snapshot and this step's own live re-fetch, so the live head no longer
    matched `HEAD_SHA`. The old check order ran the head-SHA-match check
    before the draft exemption, so it failed hard with `::error::Pull
    request head moved while validating live review state.` and exit 1
    (https://github.com/ContextualWisdomLab/contextual-orchestrator/actions/runs/33548447878/job/100066104033)
    even though no review was ever actually being requested against a
    stable target. Draft/closed must be checked before head-match so a
    still-iterating draft PR always exits 0, no matter how many pushes
    race the event snapshot.
    """
    result = _run_request_review_step(
        tmp_path, pr_draft="true", live_head_sha="f" * 40
    )
    assert result.returncode == 0, result.stderr
    assert (
        "PR is still a draft on the live exact head; a current-head OpenCode review is not requested"
        in result.stdout
    )
    assert "head moved" not in result.stdout
    assert "::error::" not in result.stdout


def test_request_review_step_exits_gracefully_when_open_nondraft_head_moved(
    tmp_path: Path,
) -> None:
    """An open, ready PR whose live head has already advanced must not error.

    A newer push already fired its own fresh `pull_request_target` event and
    its own fresh run of this workflow, which will validate *that* head
    correctly -- failing this now-superseded dispatch attempt would only add
    red-X noise for a benign race, not prevent anything.
    """
    result = _run_request_review_step(
        tmp_path, pr_draft="false", live_head_sha="f" * 40
    )
    assert result.returncode == 0, result.stderr
    assert (
        "Pull request head moved on the live open, ready-for-review PR; "
        "a fresh dispatch will fire for the current head." in result.stdout
    )
    assert "::error::" not in result.stdout


def test_fail_closed_step_exempts_a_draft_pr_whose_live_head_has_moved(
    tmp_path: Path,
) -> None:
    """The sibling "Fail closed" gate has the identical production race.

    This step independently re-fetches live PR state right after the
    "Request current-head OpenCode review execution" step exits, so a draft
    PR whose head moves between the two steps' own live lookups must still
    exempt here too, not just in the sibling step above.
    """
    result = _run_fail_closed_step(
        tmp_path, pr_action="synchronize", pr_draft="true", live_head_sha="f" * 40
    )
    assert result.returncode == 0, result.stderr
    assert (
        "PR is still a draft on the live exact head; a current-head OpenCode verdict is not required"
        in result.stdout
    )
    assert "head moved" not in result.stdout
    assert "::error::" not in result.stdout


def test_fail_closed_step_exits_gracefully_when_open_nondraft_head_moved(
    tmp_path: Path,
) -> None:
    """An open, ready PR whose live head has advanced retires quietly."""
    result = _run_fail_closed_step(
        tmp_path, pr_action="synchronize", pr_draft="false", live_head_sha="f" * 40
    )
    assert result.returncode == 0, result.stderr
    assert (
        "Pull request head moved on the live open, ready-for-review PR; "
        "a fresh run will check the current head." in result.stdout
    )
    assert "::error::" not in result.stdout


def test_fail_closed_step_exempts_a_pr_converted_to_draft(
    tmp_path: Path,
) -> None:
    """A PR converted to draft exits before reading Reviews API.

    Devin Review on `#1568` found that `converted_to_draft` was missing from
    this workflow's `pull_request_target.types`, so converting a PR to draft
    while an earlier event was running could leave an unnecessary required
    check. Including `converted_to_draft` creates an exempting run. This test
    proves the step-level exemption exits before ever
    reaching the Reviews API for the exact `PR_ACTION=converted_to_draft`
    value GitHub sends for that event (`PR_DRAFT` is always `"true"` on that
    event, mirroring GitHub's own payload).
    """
    result = _run_fail_closed_step(
        tmp_path, pr_action="converted_to_draft", pr_draft="true"
    )
    assert result.returncode == 0, result.stderr
    assert "PR is still a draft on the live exact head; a current-head OpenCode verdict is not required" in result.stdout


def test_opencode_review_trigger_reacts_to_draft_conversion() -> None:
    """The workflow's own trigger set -- not just the step body -- covers it.

    A step-level test alone cannot prove the draft exemption above is
    actually reachable in production: GitHub only re-invokes this workflow
    for event types listed in `pull_request_target.types`. This pins that
    `converted_to_draft` is present there, so a draft conversion fires a fresh
    exempting run.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    trigger_block = workflow.split("  pull_request_target:\n", 1)[1].split(
        "\n\nconcurrency:", 1
    )[0]
    assert "converted_to_draft" in trigger_block
    assert (
        "types: [opened, synchronize, reopened, ready_for_review, "
        "converted_to_draft, closed]"
    ) in trigger_block
    assert "cancel-in-progress: false" in workflow


def test_opencode_review_concurrency_group_is_live_admitted_repo_and_pr() -> None:
    """Only a live head enters the repo + PR cancellation group.

    The admission job compares event metadata with the live pull request.
    A delayed stale event exits before the target reaches concurrency, while
    a newer admitted head cancels the same PR's older target before a runner.

    Also confirms the group is JOB-level (on opencode-review-target only),
    not workflow-level: a workflow-level block would capture the
    structurally-separate cancel-superseded-opencode-review-runs job too,
    deadlocking it behind the very run it's supposed to cancel (Devin
    Review, 2026-09-03, confirmed independently before this fix landed).
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"(?m)^concurrency:", workflow)
    target_job = workflow.split("\n  opencode-review-target:\n", 1)[1].split(
        "\n  cancel-superseded-opencode-review-runs:", 1
    )[0]
    concurrency_block = target_job.split("    concurrency:\n", 1)[1].split(
        "\n    permissions:", 1
    )[0]
    assert "github.event.pull_request.head.sha || github.run_id" not in concurrency_block
    assert "github.event.pull_request.number || github.run_id" in concurrency_block
    assert "cancel-in-progress: true" in concurrency_block
    admission = workflow.split("\n  admit-current-head:\n", 1)[1].split(
        "\n  coverage-source-tree:", 1
    )[0]
    assert "live_head" in admission
    assert "live_state" in admission
    assert 'echo "admitted=false"' in admission
    assert 'echo "admitted=true"' in admission
    assert "outputs.admitted == 'true'" in target_job


def test_fail_closed_step_closed_still_takes_precedence_over_draft(tmp_path: Path) -> None:
    """The pre-existing ``closed`` early exit still runs before the new draft check."""
    result = _run_fail_closed_step(tmp_path, pr_action="closed", pr_draft="true")
    assert result.returncode == 0, result.stderr
    assert "PR closed; a current-head OpenCode verdict is not required." in result.stdout
    assert "PR is a draft" not in result.stdout


def test_fail_closed_step_checks_once_for_a_non_draft_pr(tmp_path: Path) -> None:
    """A non-draft PR performs one Reviews API read and never holds the runner."""
    result = _run_fail_closed_step(tmp_path, pr_action="synchronize", pr_draft="false")
    assert result.returncode == 17, result.stderr
    assert "unexpected gh invocation after live-state validation" in result.stderr


@pytest.mark.parametrize(
    ("reviews", "dispatches"),
    (
        ([{"id": 7, **review(state="APPROVED", body="## Verdict\nApprove")}], 0),
        ([{"id": 8, **review(state="CHANGES_REQUESTED", body="## Verdict\nRequest changes")}], 0),
        ([], 1),
        ([{"id": 9, **review(state="APPROVED", commit_id="b" * 40, body="## Verdict\nApprove")}], 1),
        ([{"id": 10, **review(state="APPROVED", body="## Pull request overview\n\ndeterministic fallback approval")}], 1),
    ),
)
def test_scheduler_wake_reuses_trusted_receipt_predicate(
    tmp_path: Path, reviews: list[dict[str, object]], dispatches: int
) -> None:
    """Only missing, stale, or fallback-only evidence wakes the scheduler."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "dispatches"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  printf '%s' "$LIVE_PR_JSON"
elif [[ "$*" == *"contents/scripts/ci/opencode_review_receipt_gate.py"* ]]; then
  python3 -c 'import base64, pathlib, sys; sys.stdout.write(base64.b64encode(pathlib.Path(sys.argv[1]).read_bytes()).decode())' "$REAL_RECEIPT_HELPER"
elif [[ "$*" == *"/pulls/7/reviews"* ]]; then
  printf '[%s]' "$FAKE_REVIEWS"
elif [[ "$*" == *"repos/ContextualWisdomLab/.github/dispatches"* ]]; then
  cat >/dev/null
  printf 'dispatch\n' >>"$DISPATCH_CALLS"
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        """#!/usr/bin/env bash
[[ "$*" == *"exchange_github_app_token"* ]] && printf '{"token":"app"}' || printf '{"value":"oidc"}'
""",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "REAL_RECEIPT_HELPER": str(RECEIPT_HELPER.resolve()),
        "FAKE_REVIEWS": json.dumps(reviews),
        "DISPATCH_CALLS": str(calls),
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "request",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://token.example",
        "OIDC_AUDIENCE": "opencode-github-action",
        "OPENCODE_API_BASE_URL": "https://api.opencode.ai",
        "TARGET_REPOSITORY": "owner/repo",
        "PR_NUMBER": "7",
        "HEAD_SHA": HEAD,
        "PR_DRAFT": "false",
        "BASE_BRANCH": "main",
        "BASE_SHA": "b" * 40,
        "HEAD_REF": "feature-branch",
        "WORKFLOW_SHA": "c" * 40,
        "GH_TOKEN": "token",
        "GITHUB_RUN_ID": "123456789",
        "LIVE_PR_JSON": json.dumps(
            {"draft": False, "head": {"sha": HEAD}, "state": "open"}
        ),
    }
    result = subprocess.run(
        ["bash", "-c", request_review_script()], env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stderr
    actual = calls.read_text(encoding="utf-8").count("dispatch") if calls.exists() else 0
    assert actual == dispatches


def test_formal_receipt_wake_reruns_the_immediately_failed_required_job() -> None:
    """The dispatch receipt wakes the exact failed run without runner polling."""
    required = WORKFLOW.read_text(encoding="utf-8")
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    assert "for attempt in" not in required
    assert "while :; do" not in required
    assert "poll_interval_seconds" not in required
    assert "180 minutes of polling" not in required
    assert "rerun-failed-jobs" in dispatched
    assert "id: formal_review_receipt" in dispatched
    assert "steps.formal_review_receipt.outcome == 'success'" in dispatched
    assert "github.event.client_payload.required_run_id != ''" in dispatched
    assert 'gh api "repos/${GH_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}"' in dispatched
    assert "select(.id == $run_id)" in dispatched
    assert 'select(.event == "pull_request_target")' in dispatched
    assert 'select(.path == ".github/workflows/opencode-review.yml")' in dispatched
    assert "select(.head_sha == $head)" in dispatched
    wake_step = dispatched.split("Wake exact-head required OpenCode workflow", 1)[1].split("\n\n      - name:", 1)[0]
    target_job = dispatched.split("  opencode-review-target:\n", 1)[1]
    target_permissions = target_job.split("    env:\n", 1)[0]
    assert "actions: write" in target_permissions
    assert (
        "needs.validate-pr-metadata.outputs.target_repository == "
        "github.repository && github.token"
    ) in wake_step
    assert "steps.opencode_app_token.outputs.token" not in wake_step
    assert "WAKE_TOKEN_SOURCE" in wake_step
    assert '"$WAKE_TOKEN_SOURCE" = "unavailable"' in wake_step
    assert "--paginate" not in wake_step
    # Identity is the immutable target-repository run id plus event/path/head;
    # do not depend on context-specific title or workflow_url rendering.
    assert "display_title ==" not in wake_step
    assert ".name | startswith(" not in wake_step
    assert 'workflow_url | contains("/actions/required_workflows/")' not in wake_step


def wake_selector(run: dict[str, object], *, head: str = HEAD, run_id: int = 42) -> str:
    """Execute the wake step's run-validation jq program in isolation."""
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required to execute the production wake selector")
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    marker = """jq -r --arg head "$PR_HEAD_SHA" --argjson run_id "$REQUIRED_RUN_ID" '"""
    start = dispatched.index(marker) + len(marker)
    end = dispatched.index("\n            ')", start)
    result = subprocess.run(
        [jq, "-r", "--arg", "head", head, "--argjson", "run_id", str(run_id), dispatched[start:end]],
        input=json.dumps(run),
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def required_run(*, run_id: int = 42, head_sha: str = HEAD, path: str = ".github/workflows/opencode-review.yml") -> dict[str, object]:
    """Build one realistic single-run GET REST API record.

    Mirrors the real shape a sibling repo sees for a run injected by the org's
    required-workflow ruleset (this repo's actual central-hub use case): `name`
    is the bare workflow name and `display_title` is a plain PR title, with no
    PR number or head SHA embedded in either -- unlike a native same-repo
    trigger, where both fields carry the rendered `run-name`.
    """
    return {
        "id": run_id,
        "head_sha": head_sha,
        "event": "pull_request_target",
        "name": "Required OpenCode Review",
        "display_title": "Fix an unrelated example bug",
        "path": path,
        "workflow_url": (
            "https://api.github.com/repos/ContextualWisdomLab/example"
            "/actions/required_workflows/9"
        ),
        "status": "completed",
        "conclusion": "failure",
    }


def test_wake_selector_matches_the_referenced_run_without_name_or_display_title() -> None:
    """The exact-id, exact-head run is matched using only id/event/path/head_sha."""
    assert wake_selector(required_run()) == "42\tcompleted\tfailure"


def test_wake_selector_rejects_a_referenced_run_with_a_different_head() -> None:
    """A referenced run whose head_sha has moved on (Devin Review, PR #1507:

    'another PR or head') must not be treated as the current PR's required run
    -- the realistic failure mode for an id-based reference, e.g. a superseded
    run or a stale/forged required_run_id.
    """
    assert wake_selector(required_run(head_sha="b" * 40)) == ""


def test_wake_selector_rejects_a_referenced_run_for_a_different_workflow() -> None:
    """A referenced run for a different required workflow (Strix) is rejected."""
    assert wake_selector(required_run(path=".github/workflows/strix.yml")) == ""


def test_formal_receipt_wakes_the_exact_head_failed_required_run(tmp_path: Path) -> None:
    """Execute the production wake script end-to-end against a fake GitHub API."""
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
if [[ "$*" == *"actions/runs/42/rerun-failed-jobs"* ]]; then exit 0; fi
if [[ "$*" == *"actions/runs/42"* ]]; then printf '%s\\n' '{json.dumps(required_run())}'; exit 0; fi
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
            "GH_TOKEN": "actions-write-token",
            "PR_HEAD_SHA": HEAD,
            "REQUIRED_RUN_ID": "42",
            "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    recorded = calls.read_text(encoding="utf-8")
    assert "actions/runs/42/rerun-failed-jobs" in recorded
    assert "repos/ContextualWisdomLab/example/actions/runs/42" in recorded
    assert "--paginate" not in recorded


def test_sibling_formal_receipt_fails_closed_without_actions_token() -> None:
    """A sibling wake without either Actions-capable PAT fails before GitHub I/O."""
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    step = dispatched.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1]
    script = textwrap.dedent(
        step.split("        run: |\n", 1)[1].split("\n\n      - name:", 1)[0]
    )
    result = subprocess.run(  # noqa: S603
        [shutil.which("bash") or "/bin/bash", "-c", script],
        env={
            **os.environ,
            "GH_TOKEN": "",
            "GH_REPOSITORY": "ContextualWisdomLab/example",
            "PR_HEAD_SHA": HEAD,
            "REQUIRED_RUN_ID": "42",
            "WAKE_TOKEN_SOURCE": "unavailable",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "Actions-capable wake credential is unavailable" in result.stdout
