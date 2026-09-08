import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_opencode_workflow_shell_syntax import _extract_run_block


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-pr.yml"


def test_codeql_pr_workflow_structure() -> None:
    """codeql-pr.yml stays required-workflow-safe: dispatch, release, then exact wake-up.

    See docs/adr/0025-codeql-required-workflow-dispatch-architecture.md.
    codeql-action/init and codeql-action/analyze are categorically disallowed
    inside a required workflow (docs/doctoring/codeql-pr-required-workflow-always-fails.md);
    this is the permanent regression guard the ADR's own follow-up asks for --
    a future edit that reintroduces either reference here would recreate the
    exact org-wide startup_failure incident that fix exists to prevent.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: CodeQL PR" in workflow
    assert "branches: [main, master, develop]" not in workflow
    # Stronger than the literal-string check above: reject ANY `branches:`
    # filter on the pull_request trigger, not just the specific old list --
    # a fixed branch-name list of any shape silently never fires for a
    # repository whose default branch isn't in that list, leaving its
    # org-required CodeQL check permanently absent rather than passing or
    # failing (confirmed live: a repository defaulting to gh-pages received
    # every other required check but no CodeQL check at all; caught by Devin
    # Review on .github#1661's gap-baseline entry for backlog item 38).
    trigger_start = workflow.index("on:\n  pull_request:")
    trigger_end = workflow.index("\n\n", trigger_start)
    trigger_lines = workflow[trigger_start:trigger_end].splitlines()
    assert not any(line.strip().startswith("branches:") for line in trigger_lines)
    assert "Do not restrict the base ref" in workflow
    assert "uses: github/codeql-action" not in workflow
    assert "detect-languages:" in workflow
    assert "java-kotlin" in workflow
    assert "-name '*.java'" in workflow
    assert "-name '*.kt'" in workflow
    assert "analyze-head:" in workflow
    # analyze-merge is required nowhere (PR #1766) and is dropped, not
    # migrated, per the ADR's explicit scope decision.
    assert "analyze-merge:" not in workflow
    assert "CodeQL merge preview" not in workflow
    assert "refs/pull/{0}/merge" not in workflow
    assert "event_type:\"codeql-scan\"" in workflow
    assert "repos/ContextualWisdomLab/.github/dispatches" in workflow
    # Reads the authenticated context codeql-scan-dispatch.yml publishes; it
    # never publishes that status from the required workflow.
    assert '--arg ctx "codeql-dispatch/${LANGUAGE}"' in workflow
    assert "commits/${PR_HEAD_SHA}/statuses" in workflow


def test_codeql_pr_shards_do_not_dispatch_and_coordinator_sends_the_full_matrix_once() -> None:
    """Shards consume verdicts; one coordinator POSTs the remaining language matrix.

    Per-language repository_dispatch runs were the 60-job ceiling: live
    2026-09-07 queued ~149 ``codeql-scan-dispatch.yml`` runs across 60 PR@SHA
    tuples because each analyze-head shard POSTed its own ``codeql-scan``.
    Language independence now lives in the handler's job matrix, so the
    required workflow may send every still-pending language in one payload.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    analyze_head = workflow.split("  analyze-head:\n", 1)[1].split(
        "  dispatch-current-head:\n", 1
    )[0]
    coordinator = workflow.split("  dispatch-current-head:\n", 1)[1]

    assert "id: dispatch" in analyze_head
    assert "repos/ContextualWisdomLab/.github/dispatches" not in analyze_head
    assert 'event_type:"codeql-scan"' not in analyze_head
    assert 'matrix:[{language:$language,"build-mode":$build_mode}]' not in workflow
    assert "required_job_id:$required_job_id" not in analyze_head
    assert "required_language:$required_language" not in analyze_head
    assert "DISPATCH_OUTCOME: ${{ steps.dispatch.outcome }}" in analyze_head
    assert workflow.count("- name: Read current-head CodeQL dispatch verdict") == 1
    assert workflow.count("- name: Release runner or enforce current-head CodeQL verdict") == 1
    assert workflow.count("- name: Dispatch current-head CodeQL scan") == 1
    assert "needs: [detect-languages, analyze-head]" in coordinator
    assert "always()" in coordinator.split("\n    runs-on:", 1)[0]
    assert "github.event.action != 'closed'" in coordinator.split("\n    runs-on:", 1)[0]
    coordinator_if = coordinator.split("\n    runs-on:", 1)[0]
    assert "github.run_attempt == 1" not in coordinator_if
    assert coordinator.count("repos/ContextualWisdomLab/.github/dispatches") == 1


def test_codeql_coordinator_dispatches_later_attempts_when_no_terminal_verdict() -> None:
    """A rerun must still POST codeql-scan if attempt 1 never dispatched.

    Live ContextualWisdomLab/.github#2028 run 34175742278 was attempt 2.
    ``github.run_attempt == 1`` skipped Dispatch current-head, so no
    codeql-scan-dispatch.yml run existed and compatibility stayed pending.
    The coordinator script already skips when every language has a terminal
    opencode-agent verdict, so later attempts are safe.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    coordinator_if = workflow.split("  dispatch-current-head:\n", 1)[1].split(
        "\n    runs-on:", 1
    )[0]
    coordinator = workflow.split("  dispatch-current-head:\n", 1)[1]

    assert "github.run_attempt == 1" not in coordinator_if
    assert "All detected CodeQL languages already have authenticated terminal verdicts" in coordinator
    assert 'event_type:"codeql-scan"' in coordinator
    assert "required_jobs:$required_jobs" in coordinator
    assert "required_run_id:$required_run_id" in coordinator
    assert "required_job_id:$required_job_id" not in coordinator
    assert "required_language:$required_language" not in coordinator
    assert "actions/runs/${REQUIRED_RUN_ID}/jobs" in coordinator
    assert "CodeQL compatibility analysis (" in coordinator


RUN_BLOCK_STEP_NAMES = (
    "Read current-head CodeQL dispatch verdict",
    "Release runner or enforce current-head CodeQL verdict",
    "Dispatch current-head CodeQL scan",
)


def test_codeql_pr_dispatch_and_release_run_blocks_are_valid_bash() -> None:
    """Both run: blocks in analyze-head must be syntactically valid Bash."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")

    if sys.platform == "win32":
        return
    bash = shutil.which("bash")
    if bash is None:
        return

    for step_name in RUN_BLOCK_STEP_NAMES:
        script = _extract_run_block(workflow_text, step_name)
        result = subprocess.run(
            [bash, "-n"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, f"{step_name}: {result.stderr}"


DISPATCH_STEP_NAME = "Read current-head CodeQL dispatch verdict"
VERDICT_STEP_NAME = "Release runner or enforce current-head CodeQL verdict"
COORDINATOR_STEP_NAME = "Dispatch current-head CodeQL scan"
_TEST_HEAD_SHA = "b" * 40
_TEST_BASE_SHA = "a" * 40
_TEST_REQUIRED_RUN_ID = "42"


def _dispatch_scan_title(
    *,
    head_sha: str = _TEST_HEAD_SHA,
    base_sha: str = _TEST_BASE_SHA,
    required_run_id: str = _TEST_REQUIRED_RUN_ID,
) -> str:
    """Return the immutable CodeQL dispatch run-name for one required shard."""
    return (
        "CodeQL Scan Dispatch ContextualWisdomLab/naruon#42@"
        f"{head_sha}/{base_sha}/{required_run_id}"
    )


def _completed_dispatch_run(
    *,
    title: str,
    run_id: int = 34173910106,
    status: str = "completed",
) -> dict:
    """Return one completed central CodeQL dispatch workflow-run fixture."""
    return {
        "id": run_id,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "status": status,
        "display_title": title,
        "name": title,
    }


def _run_verdict_read(
    tmp_path: Path,
    statuses: list[dict],
    *,
    dispatch_runs: dict | list[dict] | None = None,
    dispatch_jobs: dict | list[dict] | None = None,
    run_attempt: str = "2",
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    """Execute the real one-shot status read and verdict enforcement blocks."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    dispatch_script = _extract_run_block(workflow_text, DISPATCH_STEP_NAME)
    verdict_script = _extract_run_block(workflow_text, VERDICT_STEP_NAME)

    head_sha = _TEST_HEAD_SHA
    live_pr = {
        "head": {"sha": head_sha},
        "base": {"sha": _TEST_BASE_SHA},
        "state": "open",
    }

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'endpoint="${@: -1}"\n'
        'case "$endpoint" in\n'
        "  */pulls/*) printf '%s\\n' \"$FAKE_PULL_JSON\" ;;\n"
        "  */statuses) printf '%s\\n' \"$FAKE_STATUSES_JSON\" ;;\n"
        "  */codeql-scan-dispatch.yml/runs*) printf '%s\\n' \"$FAKE_DISPATCH_RUNS_JSON\" ;;\n"
        "  */actions/runs/*/jobs*) printf '%s\\n' \"$FAKE_DISPATCH_JOBS_JSON\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    output = tmp_path / "github-output"
    dispatch_env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(live_pr),
        "FAKE_STATUSES_JSON": json.dumps(statuses),
        "FAKE_DISPATCH_RUNS_JSON": json.dumps(
            dispatch_runs
            if isinstance(dispatch_runs, list)
            else [dispatch_runs if dispatch_runs is not None else {"workflow_runs": []}]
        ),
        "FAKE_DISPATCH_JOBS_JSON": json.dumps(
            dispatch_jobs
            if isinstance(dispatch_jobs, list)
            else [dispatch_jobs if dispatch_jobs is not None else {"jobs": []}]
        ),
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "PR_HEAD_SHA": head_sha,
        "LANGUAGE": "python",
        "BUILD_MODE": "none",
        "BASE_REF": "main",
        "BASE_SHA": _TEST_BASE_SHA,
        "HEAD_REF": "feature",
        "RUN_ATTEMPT": run_attempt,
        "REQUIRED_RUN_ID": _TEST_REQUIRED_RUN_ID,
        "REQUIRED_JOB_ID": "43",
        "GITHUB_OUTPUT": str(output),
    }
    dispatch_result = subprocess.run(
        [bash], input=dispatch_script, text=True, capture_output=True, check=False,
        env=dispatch_env, timeout=60,
    )
    output_values = {}
    if output.exists():
        output_values = dict(
            line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()
            if "=" in line
        )
    if "verdict" not in output_values:
        return dispatch_result, subprocess.CompletedProcess(
            args=[bash], returncode=1, stdout="", stderr=""
        )
    verdict_env = {
        **os.environ,
        "LANGUAGE": "python",
        "DISPATCH_OUTCOME": "success" if dispatch_result.returncode == 0 else "failure",
        "VERDICT_STATE": output_values.get("verdict", ""),
    }
    verdict_result = subprocess.run(
        [bash], input=verdict_script, text=True, capture_output=True, check=False,
        env=verdict_env, timeout=60,
    )
    return dispatch_result, verdict_result


def test_codeql_pr_one_shot_read_ignores_status_forged_by_non_opencode_creator(tmp_path: Path) -> None:
    """A PR-forged 'codeql-dispatch/<language>: success' status must not stand in for the real verdict.

    Only a status published by codeql-scan-dispatch.yml's own app identity
    (opencode-agent[bot], minted via the same OIDC exchange
    opencode-review-dispatch.yml uses) may satisfy the verdict read -- matching the
    context string alone is not enough, since anyone with statuses:write on
    the repository can publish an arbitrary context (ADR 0025, "Poll target
    cannot be spoofed by the PR author"). This proves the forged success is
    skipped in favor of the legitimate (here, failing) verdict rather than
    accepted.
    """
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[
            {"context": "codeql-dispatch/python", "state": "success", "creator": {"login": "attacker"}},
            {
                "context": "codeql-dispatch/python",
                "state": "failure",
                "creator": {"login": "opencode-agent[bot]"},
            },
        ],
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == 1, verdict_result.stderr
    assert "did not pass (state=failure)" in verdict_result.stdout


def test_codeql_pr_one_shot_read_accepts_the_opencode_agent_creator(tmp_path: Path) -> None:
    """The legitimate handler's own success status is accepted once creator identity matches."""
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[
            {
                "context": "codeql-dispatch/python",
                "state": "success",
                "creator": {"login": "opencode-agent[bot]"},
            }
        ],
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == 0, verdict_result.stderr
    assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout


@pytest.mark.parametrize("run_status,validation_status,scan_status,expected", [
    ("completed", "success", "completed", 0),
    ("in_progress", "success", "completed", 0),
    ("in_progress", "failure", "completed", 1),
    ("in_progress", "success", "in_progress", 1),
])
def test_codeql_pr_one_shot_read_accepts_completed_dispatch_scan_job_when_status_unpublishable(
    tmp_path: Path,
    run_status: str, validation_status: str, scan_status: str, expected: int,
) -> None:
    """A completed dispatch scan job is terminal evidence when statuses:write 403s.

    Live 2026-09-08 naruon#1596 dispatch run 34173910106 scanned clean, then
    POST /statuses returned HTTP 403 for opencode-agent (statuses:read only)
    and github.token (cross-repo). The required shard must consume that
    completed scan job instead of staying fail-closed on a missing status.
    """
    head_sha = _TEST_HEAD_SHA
    title = _dispatch_scan_title(head_sha=head_sha)
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        dispatch_runs={
            "workflow_runs": [
                _completed_dispatch_run(title=title, status=run_status)
            ]
        },
        dispatch_jobs={
            "jobs": [
                {
                    "name": "validate-dispatch",
                    "status": "completed",
                    "conclusion": validation_status,
                },
                {
                    "name": "CodeQL dispatch scan (python)",
                    "status": scan_status,
                    "conclusion": "success",
                }
            ]
        },
    )
    assert dispatch_result.returncode == expected, dispatch_result.stderr + dispatch_result.stdout
    assert verdict_result.returncode == expected, verdict_result.stderr + verdict_result.stdout
    if expected == 0:
        assert "completed CodeQL dispatch scan job for python: success" in dispatch_result.stdout
        assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout


def test_codeql_pr_finds_completed_dispatch_scan_beyond_first_results_page(
    tmp_path: Path,
) -> None:
    """The exact completed dispatch remains discoverable on later API pages."""
    head_sha = _TEST_HEAD_SHA
    expected_title = _dispatch_scan_title(head_sha=head_sha)
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        dispatch_runs=[
            {"workflow_runs": []},
            {"workflow_runs": [_completed_dispatch_run(title=expected_title)]},
        ],
        dispatch_jobs=[
            {"jobs": []},
            {
                "jobs": [
                    {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
                    {
                        "name": "CodeQL dispatch scan (python)",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            },
        ],
    )

    assert dispatch_result.returncode == 0, dispatch_result.stderr + dispatch_result.stdout
    assert verdict_result.returncode == 0, verdict_result.stderr + verdict_result.stdout
    assert "completed CodeQL dispatch scan job for python: success" in dispatch_result.stdout


def test_codeql_pr_rejects_completed_dispatch_scan_from_a_stale_base(
    tmp_path: Path,
) -> None:
    """Same head and language after a base retarget must not reuse the prior scan.

    A PR can keep its head SHA while the base moves. The native handler already
    binds receipts to the live base SHA; the required shard must not accept a
    completed dispatch whose run-name still names the predecessor base.
    """
    stale_title = _dispatch_scan_title(base_sha="c" * 40)
    dispatch_result, _verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        dispatch_runs={"workflow_runs": [_completed_dispatch_run(title=stale_title)]},
        dispatch_jobs={
            "jobs": [
                {
                    "name": "validate-dispatch",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "CodeQL dispatch scan (python)",
                    "conclusion": "success",
                }
            ]
        },
    )

    assert dispatch_result.returncode == 1, dispatch_result.stderr + dispatch_result.stdout
    assert "without an authenticated terminal verdict" in dispatch_result.stdout
    assert "completed CodeQL dispatch scan job for python: success" not in dispatch_result.stdout


def test_codeql_pr_rejects_completed_dispatch_scan_from_a_different_required_run(
    tmp_path: Path,
) -> None:
    """A same-PR/head/language scan for another required run cannot wake this shard.

    Language plus repository/PR/head is not enough: each waiting required job
    lives in one required-workflow run. Binding required_run_id in the
    dispatch run-name, together with the language job name, is the job
    identity the shard can observe without reading client_payload.
    """
    other_run_title = _dispatch_scan_title(required_run_id="99")
    dispatch_result, _verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        dispatch_runs={
            "workflow_runs": [_completed_dispatch_run(title=other_run_title)]
        },
        dispatch_jobs={
            "jobs": [
                {
                    "name": "validate-dispatch",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "name": "CodeQL dispatch scan (python)",
                    "conclusion": "success",
                }
            ]
        },
    )

    assert dispatch_result.returncode == 1, dispatch_result.stderr + dispatch_result.stdout
    assert "without an authenticated terminal verdict" in dispatch_result.stdout
    assert "completed CodeQL dispatch scan job for python: success" not in dispatch_result.stdout


def test_codeql_pr_fallback_binds_live_base_and_required_run_identity() -> None:
    """The required shard looks up the public dispatch run by immutable identity."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    shard = workflow.split("  analyze-head:\n", 1)[1].split(
        "  dispatch-current-head:\n", 1
    )[0]

    assert "REQUIRED_RUN_ID: ${{ github.run_id }}" in shard
    assert 'live_base="$(printf' in shard
    assert (
        'expected_title="CodeQL Scan Dispatch ${TARGET_REPOSITORY}#${PR_NUMBER}'
        '@${PR_HEAD_SHA}/${live_base}/${REQUIRED_RUN_ID}"'
    ) in shard
    assert "Could not validate live pull request base SHA before CodeQL verdict read." in shard


def test_codeql_coordinator_fallback_binds_live_base_and_required_run_identity() -> None:
    """Coordinator lookup must use the exact dispatch run identity from #2028."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    coordinator = workflow.split("  dispatch-current-head:\\n", 1)[1]

    assert (
        'expected_title="CodeQL Scan Dispatch ${TARGET_REPOSITORY}#${PR_NUMBER}'
        '@${PR_HEAD_SHA}/${live_base}/${REQUIRED_RUN_ID}"'
    ) in coordinator


def test_codeql_action_steps_use_one_version_per_workflow() -> None:
    """Prevent CodeQL init/analyze version splits from failing the scheduled scan."""
    workflow = (REPO_ROOT / ".github/workflows/scheduled-security-scan.yml").read_text(
        encoding="utf-8"
    )
    refs = set(
        re.findall(
            r"github/codeql-action/(?:init|analyze|upload-sarif)@([0-9a-f]{40})",
            workflow,
        )
    )

    assert len(refs) == 1, f"scheduled-security-scan.yml mixes CodeQL action refs: {sorted(refs)}"


def test_codeql_shard_releases_runner_and_reads_exact_head_verdict() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    shard = workflow.split("  analyze-head:\n", 1)[1].split(
        "  dispatch-current-head:\n", 1
    )[0]

    assert "while :; do" not in shard
    assert "poll_interval_seconds" not in shard
    assert "sleep " not in shard
    assert "job.check_run_id" not in shard
    assert "required_job_id:$required_job_id" not in shard
    assert "required_language:$required_language" not in shard
    assert "The dispatch workflow will rerun this exact failed CodeQL job" in shard
    assert "commits/${PR_HEAD_SHA}/statuses" in shard
    assert "repos/ContextualWisdomLab/.github/dispatches" not in shard


def test_codeql_required_workflow_does_not_gain_actions_write() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    permissions = workflow.split("permissions:\n", 1)[1].split("\njobs:\n", 1)[0]
    shard_permissions = workflow.split("  analyze-head:\n", 1)[1].split(
        "    strategy:\n", 1
    )[0]
    coordinator_permissions = workflow.split("  dispatch-current-head:\n", 1)[1].split(
        "    steps:\n", 1
    )[0]

    assert "actions: write" not in permissions
    assert "actions: write" not in shard_permissions
    assert "actions: write" not in coordinator_permissions


def test_codeql_pr_attempt_one_without_verdict_fails_pending_without_dispatch(
    tmp_path: Path,
) -> None:
    """Attempt 1 with no authenticated status releases the runner and does not POST."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    dispatch_script = _extract_run_block(workflow_text, DISPATCH_STEP_NAME)
    verdict_script = _extract_run_block(workflow_text, VERDICT_STEP_NAME)
    head_sha = "b" * 40
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    post_log = tmp_path / "posts"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'if [ "${2:-}" = "-X" ]; then\n'
        '  printf \'%s\\n\' "$4" >>"$FAKE_POST_LOG"\n'
        "  exit 0\n"
        "fi\n"
        'endpoint="${@: -1}"\n'
        'case "$endpoint" in\n'
        "  */pulls/*) printf '%s\\n' \"$FAKE_PULL_JSON\" ;;\n"
        "  */statuses) printf '%s\\n' \"$FAKE_STATUSES_JSON\" ;;\n"
        "  */codeql-scan-dispatch.yml/runs*) printf '%s\\n' \"$FAKE_DISPATCH_RUNS_JSON\" ;;\n"
        "  */actions/runs/*/jobs*) printf '%s\\n' \"$FAKE_DISPATCH_JOBS_JSON\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    output = tmp_path / "github-output"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(
            {
                "head": {"sha": head_sha},
                "base": {"sha": _TEST_BASE_SHA},
                "state": "open",
            }
        ),
        "FAKE_STATUSES_JSON": json.dumps([]),
        "FAKE_DISPATCH_RUNS_JSON": json.dumps([{"workflow_runs": []}]),
        "FAKE_DISPATCH_JOBS_JSON": json.dumps([{"jobs": []}]),
        "FAKE_POST_LOG": str(post_log),
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "PR_HEAD_SHA": head_sha,
        "LANGUAGE": "python",
        "BUILD_MODE": "none",
        "RUN_ATTEMPT": "1",
        "REQUIRED_RUN_ID": "42",
        "GITHUB_OUTPUT": str(output),
    }
    dispatch_result = subprocess.run(
        [bash], input=dispatch_script, text=True, capture_output=True, check=False,
        env=env, timeout=60,
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert "verdict=pending" in output.read_text(encoding="utf-8")
    assert not post_log.exists()
    verdict_result = subprocess.run(
        [bash],
        input=verdict_script,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "LANGUAGE": "python",
            "DISPATCH_OUTCOME": "success",
            "VERDICT_STATE": "pending",
        },
        timeout=60,
    )
    assert verdict_result.returncode == 1
    assert "CodeQL scan dispatched" in verdict_result.stdout


def _write_coordinator_fakes(
    tmp_path: Path,
    *,
    pull: dict,
    jobs: dict,
    statuses: list[dict],
) -> tuple[Path, Path, Path]:
    """Install fake gh/curl binaries and return (bin, post_log, post_body)."""
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    post_log = tmp_path / "posts"
    post_body = tmp_path / "post-body"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        "shift\n"
        "method=GET\n"
        "path=\n"
        "jq_filter=\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        "    -X) shift; method=$1 ;;\n"
        "    --input) shift; input=$1 ;;\n"
        "    --jq|-q) shift; jq_filter=$1 ;;\n"
        "    --paginate) ;;\n"
        '    repos/*) path=$1 ;;\n'
        "  esac\n"
        "  shift || true\n"
        "done\n"
        'if [ "$method" = POST ]; then\n'
        '  printf \'%s\\n\' "$path" >>"$FAKE_POST_LOG"\n'
        '  if [ "${input:-}" = "-" ]; then cat >>"$FAKE_POST_BODY"; fi\n'
        "  exit 0\n"
        "fi\n"
        "body=\n"
        'case "$path" in\n'
        "  */pulls/*) body=$FAKE_PULL_JSON ;;\n"
        "  */statuses) body=$FAKE_STATUSES_JSON ;;\n"
        "  */codeql-scan-dispatch.yml/runs) body=$FAKE_DISPATCH_RUNS_JSON ;;\n"
        "  repos/ContextualWisdomLab/.github/actions/runs/*/jobs) body=$FAKE_DISPATCH_JOBS_JSON ;;\n"
        "  */actions/runs/*/jobs) body=$FAKE_JOBS_JSON ;;\n"
        "  *) exit 1 ;;\n"
        "esac\n"
        'if [ -n "${jq_filter}" ]; then printf \'%s\\n\' "$body" | jq -c "$jq_filter"; else printf \'%s\\n\' "$body"; fi\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf \'%s\\n\' "$*" >>"$FAKE_CURL_LOG"\n'
        'if [[ " $* " == *"exchange_github_app_token"* ]]; then\n'
        "  printf '%s\\n' '{\"token\":\"fake-app-token\"}'\n"
        "  exit 0\n"
        "fi\n"
        "printf '%s\\n' '{\"value\":\"fake-oidc-token\"}'\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    (tmp_path / "pull.json").write_text(json.dumps(pull), encoding="utf-8")
    (tmp_path / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    (tmp_path / "statuses.json").write_text(json.dumps(statuses), encoding="utf-8")
    return fake_bin, post_log, post_body


def _run_coordinator(
    tmp_path: Path,
    *,
    pull: dict | None = None,
    jobs: dict | None = None,
    statuses: list[dict] | None = None,
    env_overrides: dict[str, str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    """Execute the coordinator dispatch block against fixture-backed APIs."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    head_sha = "b" * 40
    pull = pull or {
        "state": "open",
        "head": {"sha": head_sha, "ref": "feature"},
        "base": {"sha": "a" * 40, "ref": "main"},
    }
    jobs = jobs or {
        "total_count": 2,
        "jobs": [
            {
                "id": 101,
                "name": "CodeQL compatibility analysis (python)",
                "status": "completed",
                "conclusion": "failure",
            },
            {
                "id": 102,
                "name": "CodeQL compatibility analysis (actions)",
                "status": "completed",
                "conclusion": "failure",
            },
        ],
    }
    statuses = statuses if statuses is not None else []
    fake_bin, post_log, post_body = _write_coordinator_fakes(
        tmp_path, pull=pull, jobs=jobs, statuses=statuses
    )
    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), COORDINATOR_STEP_NAME
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "FAKE_JOBS_JSON": json.dumps(jobs),
        "FAKE_STATUSES_JSON": json.dumps(statuses),
        "FAKE_DISPATCH_RUNS_JSON": json.dumps([{"workflow_runs": []}]),
        "FAKE_DISPATCH_JOBS_JSON": json.dumps([{"jobs": []}]),
        "FAKE_POST_LOG": str(post_log),
        "FAKE_POST_BODY": str(post_body),
        "FAKE_CURL_LOG": str(tmp_path / "curl.log"),
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "GITHUB_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "PR_BASE_REF": "main",
        "PR_BASE_SHA": "a" * 40,
        "PR_HEAD_REF": "feature",
        "PR_HEAD_SHA": head_sha,
        "REQUIRED_RUN_ID": "99",
        "MATRIX": json.dumps(
            {
                "include": [
                    {"language": "python", "build-mode": "none"},
                    {"language": "actions", "build-mode": "none"},
                ]
            }
        ),
        "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc-request-token",
        "ACTIONS_ID_TOKEN_REQUEST_URL": "https://example.test/oidc",
        "OIDC_AUDIENCE": "opencode-github-action",
        "OPENCODE_API_BASE_URL": "https://api.opencode.ai",
        **(env_overrides or {}),
    }
    result = subprocess.run(
        [bash], input=script, text=True, capture_output=True, check=False, env=env,
        timeout=60,
    )
    return result, post_log, post_body


def test_codeql_coordinator_posts_one_dispatch_for_every_pending_language(
    tmp_path: Path,
) -> None:
    """One repository_dispatch carries every language that still needs a scan."""
    result, post_log, post_body = _run_coordinator(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/.github/dispatches"
    ]
    payload = json.loads(post_body.read_text(encoding="utf-8"))
    assert payload["event_type"] == "codeql-scan"
    client = payload["client_payload"]
    assert client["target_repository"] == "ContextualWisdomLab/naruon"
    assert client["pr_number"] == "42"
    assert client["required_run_id"] == "99"
    assert "required_job_id" not in client
    assert "required_language" not in client
    languages = [entry["language"] for entry in client["matrix"]]
    assert languages == ["python", "actions"]
    jobs_by_language = {
        entry["language"]: entry["job_id"] for entry in client["required_jobs"]
    }
    assert jobs_by_language == {"python": 101, "actions": 102}


def test_codeql_coordinator_skips_dispatch_when_every_language_has_a_verdict(
    tmp_path: Path,
) -> None:
    """A rerun that already has terminal statuses must not enqueue another scan."""
    result, post_log, post_body = _run_coordinator(
        tmp_path,
        statuses=[
            {
                "context": "codeql-dispatch/python",
                "state": "success",
                "creator": {"login": "opencode-agent[bot]"},
            },
            {
                "context": "codeql-dispatch/actions",
                "state": "failure",
                "creator": {"login": "opencode-agent[bot]"},
            },
        ],
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert not post_log.exists()
    assert not post_body.exists() or post_body.read_text(encoding="utf-8") == ""
    assert "already have authenticated terminal verdicts" in result.stdout


@pytest.mark.parametrize("scan_conclusion", ["success", "failure"])
def test_codeql_coordinator_does_not_redispatch_completed_scan_jobs(
    tmp_path: Path, scan_conclusion: str,
) -> None:
    """Terminal fallback evidence stops rescan loops, including real findings."""
    title = _dispatch_scan_title(required_run_id="99")
    result, post_log, _ = _run_coordinator(tmp_path, env_overrides={
        "FAKE_DISPATCH_RUNS_JSON": json.dumps([{"workflow_runs": [{
            "id": 123, "path": ".github/workflows/codeql-scan-dispatch.yml",
            "event": "repository_dispatch", "status": "in_progress", "display_title": title,
        }]}]),
        "FAKE_DISPATCH_JOBS_JSON": json.dumps([{"jobs": [
            {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
            *[{"name": f"CodeQL dispatch scan ({language})", "status": "completed",
               "conclusion": scan_conclusion} for language in ("python", "actions")],
        ]}]),
    })
    assert result.returncode == 0, result.stderr
    assert not post_log.exists()


def test_codeql_coordinator_fails_closed_when_a_shard_job_id_is_missing(
    tmp_path: Path,
) -> None:
    """A matrix language with no analyze-head job cannot be woken later."""
    result, post_log, _post_body = _run_coordinator(
        tmp_path,
        jobs={
            "total_count": 1,
            "jobs": [
                {
                    "id": 101,
                    "name": "CodeQL compatibility analysis (python)",
                    "status": "completed",
                    "conclusion": "failure",
                }
            ],
        },
    )

    assert result.returncode == 1
    assert "missing current-head job id" in result.stdout
    assert not post_log.exists()


def test_codeql_coordinator_dispatches_the_live_base_after_a_same_head_retarget(
    tmp_path: Path,
) -> None:
    """A retargeted PR must dispatch against the live base, not the event snapshot."""
    live_base = "c" * 40
    result, post_log, post_body = _run_coordinator(
        tmp_path,
        pull={
            "state": "open",
            "head": {"sha": "b" * 40, "ref": "feature"},
            "base": {"sha": live_base, "ref": "release"},
        },
        env_overrides={"PR_BASE_SHA": "a" * 40, "PR_BASE_REF": "main"},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/.github/dispatches"
    ]
    client = json.loads(post_body.read_text(encoding="utf-8"))["client_payload"]
    assert client["pr_base_sha"] == live_base
    assert client["pr_base_ref"] == "release"
    assert client["pr_head_sha"] == "b" * 40
    assert client["required_run_id"] == "99"


def test_codeql_coordinator_does_not_dispatch_a_closed_or_stale_pull_request(
    tmp_path: Path,
) -> None:
    """Live-head revalidation remains fail-closed before the single POST."""
    closed, closed_log, _closed_body = _run_coordinator(
        tmp_path / "closed",
        pull={
            "state": "closed",
            "head": {"sha": "b" * 40, "ref": "feature"},
            "base": {"sha": "a" * 40, "ref": "main"},
        },
    )
    stale, stale_log, _stale_body = _run_coordinator(
        tmp_path / "stale",
        pull={
            "state": "open",
            "head": {"sha": "c" * 40, "ref": "feature"},
            "base": {"sha": "a" * 40, "ref": "main"},
        },
    )

    assert closed.returncode == 0, closed.stderr
    assert stale.returncode == 0, stale.stderr
    assert not closed_log.exists()
    assert not stale_log.exists()
