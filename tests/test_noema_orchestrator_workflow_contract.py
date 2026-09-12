"""Noema review now uses the vendored orchestrator sidecar, not NVIDIA NIM."""

from __future__ import annotations

import os
import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

from tests.test_required_workflow_queue_contract import workflow_step, workflow_text


def test_noema_close_cleanup_selects_only_the_closed_pr_across_shared_display_titles(
    tmp_path: Path,
) -> None:
    """Execute cleanup against a shared-head-SHA fixture and cancel only the closed PR.

    The `cancel-closed-pr-runs` job/step retained their names, but PR #1869
    ("retire review scans when PRs return to draft") generalized this step
    to also cover `converted_to_draft`, renaming it to "...for the inactive
    pull request" and adding a `live_target_matches` re-verification against
    the live PR (mirroring `strix.yml`'s identical job) before every
    cancellation pass. This fixture drives that live lookup to a `closed`
    PR #7 at the fixture's shared head SHA so the protected invariant below
    is exercised exactly as before.

    Real jq/bash execution (not text-grepping): PR #7 (closing) and PR #8
    (unrelated, open) both have runs on the same head commit; only #7's
    matches the PR-scoped selector cancel_runs applies, and a `completed`
    PR #7 run must not be re-cancelled. Runs #104/#105 additionally cover
    Devin Review's "Sibling Noema runs evade cancellation" finding on PR
    #1507: a required-workflow-ruleset run materialized in a sibling
    repository whose `display_title` never rendered this workflow's PR/head
    run-name (a plain PR title instead) must still be matched through
    GitHub's own `pull_requests[]` array, and only for the closing PR. The
    fake `gh` below filters its fixture by the `status=` query parameter,
    mirroring GitHub's own server-side status filtering, because the
    workflow's cancel_runs deliberately relies on that filtering (see the
    run block's own comment) rather than fetching everything and filtering
    client-side.
    """
    script = textwrap.dedent(
        workflow_step(
            workflow_text("noema-review.yml"),
            "Cancel queued and running Noema reviews for the inactive pull request",
        ).split("        run: |\n", 1)[1].split("\n  noema-review:", 1)[0]
    )
    workflow_path = ".github/workflows/noema-review.yml"
    runs = {
        "workflow_runs": [
            {
                "id": 101,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "Required Noema Review ContextualWisdomLab/demo#7@" + "a" * 40,
                "head_sha": "a" * 40,
                "status": "requested",
            },
            {
                "id": 102,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "Required Noema Review ContextualWisdomLab/demo#8@" + "a" * 40,
                "head_sha": "a" * 40,
                "status": "queued",
            },
            {
                "id": 103,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "Required Noema Review ContextualWisdomLab/demo#7@" + "a" * 40,
                "head_sha": "a" * 40,
                "status": "completed",
            },
            {
                "id": 104,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "Fix an unrelated example bug",
                "head_sha": "a" * 40,
                "status": "queued",
                "pull_requests": [{"number": 7}],
            },
            {
                "id": 105,
                "path": workflow_path,
                "name": "Required Noema Review",
                "display_title": "A different pull request's title",
                "head_sha": "a" * 40,
                "status": "queued",
                "pull_requests": [{"number": 8}],
            },
        ]
    }
    runs_file = tmp_path / "runs.json"
    runs_file.write_text(json.dumps(runs), encoding="utf-8")
    calls_file = tmp_path / "calls.txt"
    # The closing PR's live state, returned by the `live_target_matches`
    # re-verification `cancel_runs` performs before every status query and
    # before every individual cancellation (added by PR #1869 alongside the
    # `converted_to_draft` generalization; mirrors strix.yml's identical
    # job). Head SHA matches the fixture runs above so the closed-PR-#7
    # cleanup is verified live and proceeds exactly as before that change.
    live_pr_json = json.dumps({"state": "closed", "draft": False, "head": {"sha": "a" * 40}})
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"--paginate"* ]]; then
  [[ "$*" != *"/actions/workflows/"* ]] || exit 99
  printf '%s\n' "$*" >>"$FAKE_CALLS_FILE"
  url="$3"
  status="$(printf '%s' "$url" | sed -E 's/.*status=([a-z_]+)&.*/\\1/')"
  jq --arg status "$status" '{workflow_runs: [.workflow_runs[] | select(.status == $status)]}' \\
    "$FAKE_RUNS_FILE"
elif [[ "$*" == "api repos/ContextualWisdomLab/demo/pulls/7" ]]; then
  printf '%s\n' "$*" >>"$FAKE_CALLS_FILE"
  printf '%s\n' "$FAKE_LIVE_PR_JSON"
else
  printf '%s\n' "$*" >>"$FAKE_CALLS_FILE"
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(  # noqa: S603
        [shutil.which("bash") or "/bin/bash", "-c", script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "TARGET_REPOSITORY": "ContextualWisdomLab/demo",
            "INACTIVE_PR_NUMBER": "7",
            "INACTIVE_PR_HEAD_SHA": "a" * 40,
            "PR_ACTION": "closed",
            "CURRENT_RUN_ID": "999",
            "FAKE_RUNS_FILE": str(runs_file),
            "FAKE_CALLS_FILE": str(calls_file),
            "FAKE_LIVE_PR_JSON": live_pr_json,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    calls = calls_file.read_text(encoding="utf-8")
    # Repository-scoped, status-server-filtered -- never the workflow-file-
    # scoped endpoint, which does not resolve for sibling-repository runs.
    assert "actions/runs?status=" in calls
    assert "/actions/workflows/" not in calls
    assert "/actions/runs/101/cancel" in calls
    assert "/actions/runs/102/cancel" not in calls
    assert "/actions/runs/103/cancel" not in calls
    # Devin Review finding on PR #1507 ("Sibling Noema runs evade
    # cancellation"): a required-workflow-ruleset run materialized in a
    # sibling repository (#104) never renders this workflow's run-name into
    # display_title, so it must still be matched via GitHub's own
    # pull_requests[] array; a same-shaped run for an unrelated PR (#105)
    # must not.
    assert "/actions/runs/104/cancel" in calls
    assert "/actions/runs/105/cancel" not in calls


def test_noema_review_credentials_and_llm_use_orchestrator_free() -> None:
    """Require reviewer credentials and the sidecar; the public NIM hardcode is gone."""
    workflow = workflow_text("noema-review.yml")

    assert "fail_unavailable()" in workflow
    assert 'echo "::error::$message"' in workflow
    assert "vars.NOEMA_TOKEN_EXCHANGE_URL || vars.NOEMA_EXCHANGE_URL || ''" in workflow
    assert (
        "Noema reviewer credential is unconfigured: set NOEMA_GITHUB_APP_CLIENT_ID with "
        "NOEMA_GITHUB_APP_PRIVATE_KEY, NOEMA_REVIEW_TOKEN, or NOEMA_TOKEN_EXCHANGE_URL. "
        "Review cannot be skipped."
    ) in workflow
    assert (
        "Noema reviewer credential selection succeeded but no token was minted"
        in workflow
    )
    assert "https://integrate.api.nvidia.com/v1/chat/completions" not in workflow
    assert "nvidia/nemotron-3-ultra-550b-a55b" not in workflow
    assert "Resolve Noema target repository visibility" in workflow
    assert "target_visibility.outputs.require_zdr" in workflow
    assert "CONTEXTUAL_ORCHESTRATOR_REQUIRE_ZDR" in workflow
    assert (
        "NOEMA_LLM_API_KEY: ${{ secrets.NOEMA_LLM_API_KEY || secrets.OPENAI_API_KEY || '' }}"
        not in workflow
    )
    assert "contextual_orchestrator_review_sidecar.sh" in workflow
    assert "BYTEZ_API_KEY: ${{ secrets.BYTEZ_API_KEY }}" in workflow
    assert "NVIDIA_NIM_API_KEY: ${{ secrets.NVIDIA_NIM_API_KEY }}" in workflow
    assert "NVIDIA_NIM_API_KEY_SUB: ${{ secrets.NVIDIA_NIM_API_KEY_SUB }}" in workflow
    assert "OPENROUTER_API_KEY: ${{ secrets.OPENROUTER_API_KEY }}" in workflow
    assert "OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}" in workflow
    assert 'export NOEMA_LLM_MODEL="orchestrator/free"' in workflow
    prepare = workflow_step(workflow, "Prepare Noema model verdict")
    publish = workflow_step(workflow, "Publish prepared Noema verdict on the exact live head")
    assert '.github/actions/noema-review/two_phase.py' in prepare
    assert '--prepare-verdict-file "$verdict_file"' in prepare
    assert '.github/actions/noema-review/two_phase.py' in publish
    assert '--publish-verdict-file "$verdict_file"' in publish
    assert "python3 -m scripts.ci.noema_review_gate" not in workflow
    assert (
        "contextual-orchestrator review sidecar must be provisioned before Noema LLM review."
        in workflow
    )
    assert "mark_unconfigured()" not in workflow
    assert "review skipped until Noema is deployed" not in workflow
    assert "Noema app token is unavailable; review skipped." not in workflow
    assert "COPILOT_GITHUB_TOKEN" not in workflow
    assert "secrets: inherit" not in workflow


def _expected_head_from_workflow_run_event(event: dict) -> str:
    """Mirror EXPECTED_HEAD's ``||`` fallback chain for a ``workflow_run`` event.

    Reproduces GitHub Actions' short-circuit-on-falsy ``||`` semantics over
    the same dotted paths ``noema-review.yml``'s ``EXPECTED_HEAD`` env var
    reads, so a test can prove — with concrete, distinct base vs. PR-head SHA
    values — which commit the expression actually resolves to, without
    needing a live Actions runner to evaluate ``${{ }}`` syntax.
    """
    client_payload = event.get("client_payload") or {}
    pull_request = event.get("pull_request") or {}
    workflow_run = event.get("workflow_run") or {}
    pull_requests = workflow_run.get("pull_requests") or []
    workflow_run_pr_head = (
        (pull_requests[0].get("head") or {}).get("sha") if pull_requests else None
    )
    return (
        client_payload.get("pr_head_sha")
        or (pull_request.get("head") or {}).get("sha")
        or workflow_run_pr_head
        or ""
    )


def test_standalone_noema_expected_head_uses_trusted_trigger_context() -> None:
    """Standalone Noema binds review work to the PR or dispatch head."""
    workflow = workflow_text("noema-review.yml")
    assert (
        "EXPECTED_HEAD_SHA: ${{ github.event.pull_request.head.sha || "
        "github.event.client_payload.pr_head_sha || '' }}"
    ) in workflow
    assert "github.event.workflow_run" not in workflow


def test_workflow_run_expected_head_fails_closed_when_pull_requests_is_empty() -> None:
    """The retired workflow_run trigger cannot fabricate Noema review context."""
    assert "workflow_run:" not in workflow_text("noema-review.yml")
    workflow_run_event = {"workflow_run": {"head_sha": "c" * 40, "pull_requests": []}}
    assert _expected_head_from_workflow_run_event(workflow_run_event) == ""


def _run_stale_trigger_step(
    tmp_path: Path, *, expected_head: str, live_head: str
) -> subprocess.CompletedProcess[str]:
    """Execute the "Reject a stale trigger" step's bash with a fake `gh` on PATH."""
    bash_executable = shutil.which("bash") or "/bin/bash"
    step_script = textwrap.dedent(
        workflow_step(
            workflow_text("noema-review.yml"),
            "Reject a stale trigger before credential or model setup",
        ).split("        run: |\n", 1)[1]
    )
    fake_gh = tmp_path / "gh"
    calls_file = tmp_path / "calls.txt"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"printf '%s\\n' \"$*\" >>'{calls_file}'\n"
        "if [[ \"$*\" == 'api repos/ContextualWisdomLab/example/pulls/7 --jq .head.sha' ]]; then\n"
        f"  printf '%s' '{live_head}'\n"
        "else\n"
        "  echo 'unexpected gh invocation' >&2\n"
        "  exit 1\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
        "TARGET_REPOSITORY": "ContextualWisdomLab/example",
        "PR_NUMBER": "7",
        "EXPECTED_HEAD_SHA": expected_head,
        "GH_TOKEN": "synthetic-token",
    }
    return subprocess.run(  # noqa: S603, S607
        [bash_executable, "-c", step_script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_noema_admission_retires_out_of_order_dispatch_before_concurrency(
    tmp_path: Path,
) -> None:
    """A stale dispatch exits cleanly with admitted=false before model work."""
    bash_executable = shutil.which("bash") or "/bin/bash"
    step_script = textwrap.dedent(
        workflow_step(
            workflow_text("noema-review.yml"),
            "Admit only the exact live Noema head",
        ).split("        run: |\n", 1)[1]
    )
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nprintf '%s' '{\"head\":{\"sha\":\"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\"},\"state\":\"open\"}'\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    output = tmp_path / "github-output"
    result = subprocess.run(
        [bash_executable, "-c", step_script],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
            "GH_TOKEN": "synthetic-token",
            "GITHUB_OUTPUT": str(output),
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "7",
            "EXPECTED_HEAD_SHA": "a" * 40,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8").splitlines() == ["admitted=false"]
    assert "retired a stale trigger" in result.stdout


def test_stale_trigger_step_rejects_noncanonical_uppercase_head(
    tmp_path: Path,
) -> None:
    """Reject caller-controlled uppercase SHA before any model work."""
    sha = "a" * 40
    result = _run_stale_trigger_step(tmp_path, expected_head=sha.upper(), live_head=sha)
    assert result.returncode == 1
    assert "canonical lowercase exact head SHA" in result.stdout


def test_stale_trigger_step_still_rejects_a_genuinely_different_head(
    tmp_path: Path,
) -> None:
    """A canonical but genuinely different trigger head is still rejected."""
    result = _run_stale_trigger_step(
        tmp_path, expected_head="a" * 40, live_head="b" * 40
    )
    assert result.returncode == 1
    assert "Noema trigger is stale" in result.stdout


def test_noema_visibility_lookup_retries_transient_api_failures() -> None:
    """Bound transient GitHub API failures without weakening visibility validation."""
    workflow = workflow_text("noema-review.yml")
    start = workflow.index("      - name: Resolve Noema target repository visibility")
    end = workflow.index("      - name: Provision contextual-orchestrator review sidecar", start)
    visibility_step = workflow[start:end]

    assert "for target_visibility_attempt in 1 2 3 4 5 6; do" in visibility_step
    assert 'if visibility="$(' in visibility_step
    assert 'sleep "$(( target_visibility_attempt * 5 ))"' in visibility_step
    assert "possibly a transient GitHub API rate limit; retrying after backoff." in visibility_step
    assert "case \"$visibility\" in" in visibility_step


def test_strix_gateway_default_and_noema_sidecar_fail_closed(tmp_path: Path) -> None:
    """Keep Strix on the gateway; Noema still fails closed without its sidecar."""
    bash_executable = shutil.which("bash") or "/bin/bash"
    strix_output = tmp_path / "strix-output"
    strix = subprocess.run(  # noqa: S603, S607
        [
            bash_executable,
            "-c",
            textwrap.dedent(
                workflow_step(
                    workflow_text("strix.yml"),
                    "Gate Strix secrets",
                )
                .split("        run: |\n", 1)[1]
            ),
        ],
        env={
            **os.environ,
            "GITHUB_OUTPUT": str(strix_output),
            "STRIX_MODEL": "contextual-orchestrator/orchestrator/free",
            "STRIX_MODEL_REQUESTED": "",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert strix.returncode == 0, strix.stderr
    assert {
        "strix_model=contextual-orchestrator/orchestrator/free",
        "enabled=true",
        "provider_mode=contextual_orchestrator",
    } <= set(strix_output.read_text().splitlines())
    assert (
        "STRIX_MODEL: contextual-orchestrator/orchestrator/free"
        in workflow_text("strix.yml")
    )
    assert (
        "STRIX_MODEL: ${{ steps.gate.outputs.strix_model }}"
        in workflow_text("strix.yml")
    )

    noema_script = textwrap.dedent(
        workflow_step(
            workflow_text("noema-review.yml"),
            "Prepare Noema model verdict",
        ).split("        run: |\n", 1)[1]
    )
    noema_env = {
        **os.environ,
        "PR_NUMBER": "1",
        "GH_TOKEN": "synthetic-review-token",
    }
    for key in (
        "CONTEXTUAL_ORCHESTRATOR_BASE_URL",
        "CONTEXTUAL_ORCHESTRATOR_TOKEN",
        "NOEMA_LLM_VIA_ORCHESTRATOR",
        "NOEMA_LLM_API_KEY",
    ):
        noema_env.pop(key, None)
    noema = subprocess.run(  # noqa: S603, S607
        [bash_executable, "-c", noema_script],
        env=noema_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert noema.returncode == 1
    assert "sidecar must be provisioned before Noema LLM review" in noema.stdout


def test_cancel_closed_pr_runs_has_a_bounded_runtime() -> None:
    """cancel-closed-pr-runs must not fall back to GitHub's 360-minute default.

    Its only step is a single-repository, status-filtered gh api --paginate
    list-and-cancel sweep (up to 3 passes x 5 statuses) with no branch update
    or merge -- comparable to, or lighter than, pr-review-merge-scheduler.yml's
    scan-pr-queue job, which PR #1702 bounded to timeout-minutes: 30 for a
    single-repository scan that also dispatches a review and updates a branch.
    """
    workflow = workflow_text("noema-review.yml")
    job = workflow.split("  cancel-closed-pr-runs:\n", 1)[1].split("\n  noema-review:\n", 1)[0]

    match = re.search(r"^    timeout-minutes: (\d+)$", job, flags=re.MULTILINE)
    assert match is not None, "cancel-closed-pr-runs must declare a job-level timeout-minutes"
    timeout = int(match.group(1))
    assert 1 <= timeout <= 30
    assert timeout < 360


def test_noema_review_job_has_no_job_level_timeout() -> None:
    """noema-review must not carry a job-level timeout-minutes.

    Its "Prepare Noema model verdict" step calls two_phase.py's call_llm
    synchronously via the contextual-orchestrator gateway and blocks on the
    model's own response -- a job-level wall-clock bound here directly caps
    the model's reasoning/tool-use time once elapsed, which
    docs/product-goal-directive.md #8 prohibits ("Model timeout은
    application·Agent·Gateway 공통 상한 없이 기본 null이다"). An earlier
    version of this job set timeout-minutes: 210, reasoning it gave that
    step "the same ~180-minute allowance" opencode-review.yml's
    poll_deadline_epoch gives an unrelated step -- that reasoning was
    itself the mistake: poll_deadline_epoch bounds a step that polls GitHub
    for whether a *separately triggered* review process has posted a
    verdict yet (an async external wait), not a step that itself runs the
    model synchronously. Any fixed cap on a job whose body IS the
    synchronous model call is exactly the forbidden inference-time cap. See
    docs/doctoring/autofix-and-noema-review-model-job-timeout-removal.md.
    """
    workflow = workflow_text("noema-review.yml")
    job = workflow.split("  noema-review:\n", 1)[1]

    match = re.search(r"^    timeout-minutes: (\d+)$", job, flags=re.MULTILINE)
    assert match is None, (
        "noema-review must not declare a job-level timeout-minutes -- its "
        "body is a synchronous model call, so any job-level bound caps "
        "model inference time, which this org's model-timeout policy forbids"
    )

    assert (
        "모델당 두 시간 이상 걸릴 수 있음을 수용한다"
        in (Path(__file__).resolve().parents[1] / "docs" / "product-goal-directive.md").read_text(
            encoding="utf-8"
        )
    ), "the two-hour-per-model allowance this bound relies on must still be documented"


def test_noema_review_uploads_sidecar_evidence_on_failure() -> None:
    """A failed verdict phase ships the sanitized sidecar stderr and preflight report.

    Before this step a failed Noema run left ``artifacts=0`` (run 33981136873:
    3122 s, then HTTP 502, no per-route trace in the job log). The stderr file
    is the sidecar sanitizer's bounded allowlist output -- the same file Strix
    already publishes in ``strix-reports`` -- so shipping it on failure adds
    diagnosis without adding exposure (#1935 follow-up).
    """
    workflow = workflow_text("noema-review.yml")
    name = "Upload contextual-orchestrator sidecar evidence on failure"
    step = workflow_step(workflow, name)
    assert "if: failure() && env.PR_NUMBER != ''" in step
    strix_pin = re.search(
        r"actions/upload-artifact@([0-9a-f]{40})", workflow_text("strix.yml")
    ).group(1)
    assert f"actions/upload-artifact@{strix_pin}" in step
    assert "name: noema-sidecar-evidence" in step
    assert "strix_runs/contextual-orchestrator-sidecar.stderr.log" in step
    assert "strix_runs/contextual-orchestrator-preflight.json" in step
    assert "if-no-files-found: ignore" in step
    assert "retention-days: 5" in step
    prepare = workflow.index("      - name: Prepare Noema model verdict\n")
    upload = workflow.index(f"      - name: {name}\n")
    refresh = workflow.index(
        "      - name: Refresh repository-scoped Noema GitHub App token for publication\n"
    )
    assert prepare < upload < refresh
    assert workflow.count("actions/upload-artifact@") == 1
