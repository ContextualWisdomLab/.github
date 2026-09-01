"""Regression coverage for the runtime required current-head OpenCode verdict gate."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path

import pytest


HEAD = "a" * 40
WORKFLOW = Path(".github/workflows/opencode-review.yml")
DISPATCH_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
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


def test_request_review_execution_step_is_also_gated_on_draft() -> None:
    """The dispatch step's own gate must be the live verdict alone.

    ``Fail closed without a current-head OpenCode verdict`` exempts drafts
    and closed PRs via ``steps.verdict.outputs.verdict``, which the verdict
    step now resolves from the pull request's *live* state. The earlier
    ``Request current-head OpenCode review execution`` step must gate on
    that same live signal alone -- gating it (also) on
    ``github.event.action``/``github.event.pull_request.draft`` would let a
    manual re-run of an old closed/draft-era job suppress the dispatch for a
    since-reopened/ready PR at the same head SHA using those stale payload
    fields, even though the verdict step's own live-state fix means a real
    dispatch is exactly what's needed then (Devin review on #1443).
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    lines = workflow.splitlines()
    step_index = next(
        index
        for index, line in enumerate(lines)
        if line.strip() == "- name: Request current-head OpenCode review execution"
    )
    if_line = next(
        line.strip()
        for line in lines[step_index + 1 :]
        if line.strip().startswith("if:")
    )
    assert if_line == "if: steps.verdict.outputs.verdict == ''"


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


def _write_reviews_gh(
    bin_dir: Path,
    reviews: list[dict[str, object]],
    *,
    pr_state: str = "open",
    pr_draft: bool = False,
    base_ref: str = "main",
    base_sha: str = "b" * 40,
    head_ref: str = "feature",
    head_sha: str = HEAD,
) -> Path:
    """Install a fake ``gh`` on PATH serving a live PR object, then Reviews API page.

    The production step now fetches the pull request's own live state
    (``pulls/<number>``, no ``--paginate``) before the paginated Reviews API
    call, so this fixture dispatches on the presence of ``--paginate`` in the
    arguments rather than assuming only one ``gh api`` shape is ever called.
    The live PR object also carries ``base``/``head`` refs/shas, mirroring
    what the production step now exposes as step outputs for the dispatch
    step's payload.
    """
    fake_gh = bin_dir / "gh"
    pr_fixture = bin_dir / "pr.json"
    reviews_fixture = bin_dir / "reviews.json"
    pr_fixture.write_text(
        json.dumps(
            {
                "state": pr_state,
                "draft": pr_draft,
                "base": {"ref": base_ref, "sha": base_sha},
                "head": {"ref": head_ref, "sha": head_sha},
            }
        ),
        encoding="utf-8",
    )
    reviews_fixture.write_text(json.dumps(reviews), encoding="utf-8")
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        "if [[ \" $* \" == *' --paginate '* ]]; then\n"
        f"  cat {reviews_fixture}\n"
        "else\n"
        f"  cat {pr_fixture}\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)
    return fake_gh


def _write_closed_or_draft_gh(bin_dir: Path, *, pr_state: str, pr_draft: bool) -> Path:
    """Install a fake ``gh`` on PATH that serves only the live PR object.

    Used for closed/draft cases that must short-circuit before any Reviews
    API call, mirroring ``_write_refusing_gh``'s "prove the early exit"
    intent but for the live-state call that now precedes it.
    """
    fake_gh = bin_dir / "gh"
    pr_fixture = bin_dir / "pr.json"
    pr_fixture.write_text(
        json.dumps(
            {
                "state": pr_state,
                "draft": pr_draft,
                "base": {"ref": "main", "sha": "b" * 40},
                "head": {"ref": "feature", "sha": HEAD},
            }
        ),
        encoding="utf-8",
    )
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        "if [[ \" $* \" == *' --paginate '* ]]; then\n"
        "  echo 'unexpected Reviews API call: the early-exit should have short-circuited' >&2\n"
        "  exit 17\n"
        "fi\n"
        f"cat {pr_fixture}\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)
    return fake_gh


def _run_verdict_step(
    tmp_path: Path,
    *,
    pr_number: str = "",
    head_sha: str = "",
    gh_fixture: str = "refuse",
    pr_state: str = "open",
    pr_draft: bool = False,
    reviews: list[dict[str, object]] | None = None,
    base_ref: str = "main",
    base_sha: str = "b" * 40,
    head_ref: str = "feature",
    live_head_sha: str = HEAD,
) -> subprocess.CompletedProcess[str]:
    """Execute the "Resolve current-head formal OpenCode verdict" step body.

    The production step decides closed/draft from the pull request's own
    live state (a ``gh api repos/.../pulls/<number>`` call), never from the
    triggering event's own stored payload -- so ``pr_state``/``pr_draft``
    drive a fake ``gh``'s live-PR-object response, not env vars. ``gh_fixture``
    selects which fake ``gh`` goes on PATH: ``"refuse"`` fails loudly if
    invoked at all (proving the missing-PR_NUMBER/HEAD_SHA guard runs before
    any API call), ``"closed_or_draft"`` serves only the live PR object and
    fails loudly on a Reviews API call (proving that early exit short-circuits
    before it), and ``"reviews"`` serves the live PR object and then
    ``reviews`` from the paginated Reviews API call. The step's
    ``$GITHUB_OUTPUT`` writes are captured in ``tmp_path / "github_output"``
    for the caller to inspect.
    """
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production step body")

    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = _extract_run_block(
        workflow, "Resolve current-head formal OpenCode verdict"
    )

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if gh_fixture == "refuse":
        _write_refusing_gh(bin_dir)
    elif gh_fixture == "closed_or_draft":
        _write_closed_or_draft_gh(bin_dir, pr_state=pr_state, pr_draft=pr_draft)
    else:
        _write_reviews_gh(
            bin_dir,
            reviews or [],
            pr_state=pr_state,
            pr_draft=pr_draft,
            base_ref=base_ref,
            base_sha=base_sha,
            head_ref=head_ref,
            head_sha=live_head_sha,
        )

    output_file = tmp_path / "github_output"
    output_file.write_text("", encoding="utf-8")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/example",
        "PR_NUMBER": pr_number,
        "HEAD_SHA": head_sha,
        "GITHUB_OUTPUT": str(output_file),
    }
    return subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


def _run_fail_closed_step(verdict: str) -> subprocess.CompletedProcess[str]:
    """Execute the trivial "Fail closed without a current-head OpenCode
    verdict" step body given a resolved ``$VERDICT``.

    Unlike the old design, this step no longer calls ``gh`` or loops at all
    -- the Reviews API call moved entirely into the verdict-resolution step
    above, so this one only ever inspects the ``VERDICT`` string it is
    handed.
    """
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is required to execute the production step body")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, STEP_NAME)
    return subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "VERDICT": verdict},
    )


def test_draft_pr_verdict_step_short_circuits_before_the_reviews_api_call(
    tmp_path: Path,
) -> None:
    """A draft PR's verdict step passes without ever calling the Reviews API.

    The merge scheduler (``scripts/ci/pr_review_merge_scheduler.py``) never
    dispatches a review request for a draft PR, so this required check must
    not demand a verdict that was never going to be requested. The live PR
    object (not a stale event field) is the source of the draft state, and
    the fake ``gh`` refuses any Reviews API call to prove the early-exit
    short-circuits before it.
    """
    result = _run_verdict_step(
        tmp_path,
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="closed_or_draft",
        pr_state="open",
        pr_draft=True,
    )
    assert result.returncode == 0, result.stderr
    assert "PR is a draft" in result.stdout
    assert "verdict=DRAFT" in (tmp_path / "github_output").read_text(encoding="utf-8")


def test_draft_pr_verdict_step_ignores_the_stale_triggering_event_action(
    tmp_path: Path,
) -> None:
    """A stale re-run of an old event must not resurrect a bypass.

    Regardless of which event originally triggered this run (opened,
    synchronize, reopened, converted_to_draft -- even a replayed old run),
    the verdict step now asks GitHub for the pull request's live state
    instead of trusting that event's own stored payload, so a live draft PR
    is exempted the same way no matter which stale action label the
    original workflow run happened to carry (Devin review on #1443, on the
    inverse of this case: a stale run must not falsely claim draft either).
    """
    result = _run_verdict_step(
        tmp_path,
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="closed_or_draft",
        pr_state="open",
        pr_draft=True,
    )
    assert result.returncode == 0, result.stderr
    assert "PR is a draft" in result.stdout


def test_ready_for_review_pr_still_requires_a_current_head_verdict(
    tmp_path: Path,
) -> None:
    """Once a PR is not a draft, the real gate still runs unchanged."""
    result = _run_verdict_step(
        tmp_path,
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="reviews",
        pr_state="open",
        pr_draft=False,
        reviews=[review(state="APPROVED")],
    )
    assert result.returncode == 0, result.stderr
    assert "Current-head OpenCode verdict: APPROVED." in result.stdout
    assert "verdict=APPROVED" in (tmp_path / "github_output").read_text(encoding="utf-8")


def test_non_draft_pr_without_a_verdict_leaves_the_gate_empty(tmp_path: Path) -> None:
    """A non-draft PR with no matching review resolves an empty verdict."""
    result = _run_verdict_step(
        tmp_path,
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="reviews",
        pr_state="open",
        pr_draft=False,
        reviews=[],
    )
    assert result.returncode == 0, result.stderr
    assert "verdict=" in (tmp_path / "github_output").read_text(encoding="utf-8")
    assert "verdict=APPROVED" not in (tmp_path / "github_output").read_text(encoding="utf-8")
    assert "verdict=CHANGES_REQUESTED" not in (tmp_path / "github_output").read_text(
        encoding="utf-8"
    )
    assert _run_fail_closed_step("").returncode == 1


def test_verdict_step_exposes_live_base_and_head_for_the_dispatch_payload(
    tmp_path: Path,
) -> None:
    """The verdict step's live fetch also feeds the dispatch step's payload.

    A manual re-run of an old workflow run replays github.event.pull_request's
    stored base/head refs/shas verbatim; if the base branch has since
    advanced, opencode-review-dispatch.yml's live validate-pr-metadata check
    hard-rejects that stale base_sha, so a dispatch that the verdict step
    correctly decided is needed would still fail to actually request a
    review (Devin review on #1443). base_ref/base_sha/head_ref/head_sha are
    now emitted as step outputs from the same live gh api response the
    verdict decision itself uses, deliberately using values distinct from
    the event-derived HEAD_SHA env var passed in below to prove they come
    from the live fetch, not from the caller's env.
    """
    live_head = "c" * 40
    result = _run_verdict_step(
        tmp_path,
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="reviews",
        pr_state="open",
        pr_draft=False,
        reviews=[],
        base_ref="release/live",
        base_sha="d" * 40,
        head_ref="feature/live",
        live_head_sha=live_head,
    )
    assert result.returncode == 0, result.stderr
    output = (tmp_path / "github_output").read_text(encoding="utf-8")
    assert "base_ref=release/live" in output
    assert f"base_sha={'d' * 40}" in output
    assert "head_ref=feature/live" in output
    assert f"head_sha={live_head}" in output


def test_dispatch_step_payload_sources_base_and_head_from_the_verdict_step() -> None:
    """The dispatch step must build its payload from live outputs, not the event.

    ``steps.verdict.outputs.base_ref``/``base_sha``/``head_ref``/``head_sha``
    replace the former ``github.event.pull_request.base.ref``/``base.sha``/
    ``head.ref``/``head.sha`` reads in this step's own ``env:`` block.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    dispatch_step = workflow.split(
        "- name: Request current-head OpenCode review execution", 1
    )[1].split("- name: Fail closed", 1)[0]
    assert "steps.verdict.outputs.base_ref" in dispatch_step
    assert "steps.verdict.outputs.base_sha" in dispatch_step
    assert "steps.verdict.outputs.head_ref" in dispatch_step
    assert "steps.verdict.outputs.head_sha" in dispatch_step
    assert "github.event.pull_request.base.ref" not in dispatch_step
    assert "github.event.pull_request.base.sha" not in dispatch_step
    assert "github.event.pull_request.head.ref" not in dispatch_step
    assert "github.event.pull_request.head.sha" not in dispatch_step


def test_closed_pr_short_circuits_before_the_draft_check(tmp_path: Path) -> None:
    """The pre-existing ``closed`` early-exit still takes precedence over draft."""
    result = _run_verdict_step(
        tmp_path,
        pr_number="1437",
        head_sha=HEAD,
        gh_fixture="closed_or_draft",
        pr_state="closed",
        pr_draft=True,
    )
    assert result.returncode == 0, result.stderr
    assert "PR closed; a current-head OpenCode verdict is not required." in result.stdout
    assert "PR is a draft" not in result.stdout
    assert "verdict=CLOSED" in (tmp_path / "github_output").read_text(encoding="utf-8")


def test_verdict_step_fails_closed_when_live_pr_state_is_unavailable(
    tmp_path: Path,
) -> None:
    """A failed live-state lookup fails closed instead of silently proceeding."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production step body")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, "Resolve current-head formal OpenCode verdict")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nexit 1\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | stat.S_IEXEC)
    output_file = tmp_path / "github_output"
    output_file.write_text("", encoding="utf-8")
    result = subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "GH_TOKEN": "fake-token",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "1437",
            "HEAD_SHA": HEAD,
            "GITHUB_OUTPUT": str(output_file),
        },
    )
    assert result.returncode == 1
    assert "Could not fetch the pull request's live state" in result.stdout


def test_fail_closed_step_passes_on_draft_verdict() -> None:
    """The trivial fail-closed step treats VERDICT=DRAFT like VERDICT=CLOSED."""
    result = _run_fail_closed_step("DRAFT")
    assert result.returncode == 0, result.stderr


def test_fail_closed_step_passes_on_closed_verdict() -> None:
    """The trivial fail-closed step still passes VERDICT=CLOSED unchanged."""
    result = _run_fail_closed_step("CLOSED")
    assert result.returncode == 0, result.stderr


def test_fail_closed_step_fails_without_a_verdict() -> None:
    """The trivial fail-closed step still fails closed on an empty verdict."""
    result = _run_fail_closed_step("")
    assert result.returncode == 1
    assert "No APPROVED or CHANGES_REQUESTED from opencode-agent" in result.stdout


def test_formal_receipt_reruns_failed_required_job_without_runner_polling() -> None:
    """A formal receipt wakes the failed required run instead of polling for hours."""
    required = WORKFLOW.read_text(encoding="utf-8")
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    assert "for attempt in" not in required
    assert "rerun-failed-jobs" in dispatched
    assert '--argjson required_run_id "$GITHUB_RUN_ID"' in required
    assert "required_run_id:$required_run_id" in required
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
