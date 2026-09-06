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


def test_codeql_pr_dispatches_one_language_per_shard_not_the_full_matrix() -> None:
    """Every shard dispatches, but only its own language, not the full matrix.

    Each shard carries its own run, job, language, and head identity so the
    trusted dispatcher can wake only that intentionally failed job.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "id: dispatch" in workflow
    assert 'matrix:[{language:$language,"build-mode":$build_mode}]' in workflow
    assert "needs.detect-languages.outputs.matrix).include[0]" not in workflow
    assert "DISPATCH_OUTCOME: ${{ steps.dispatch.outcome }}" in workflow
    assert workflow.count("- name: Request current-head CodeQL scan dispatch") == 1
    assert workflow.count("- name: Release runner or enforce current-head CodeQL verdict") == 1


RUN_BLOCK_STEP_NAMES = (
    "Request current-head CodeQL scan dispatch",
    "Release runner or enforce current-head CodeQL verdict",
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


DISPATCH_STEP_NAME = "Request current-head CodeQL scan dispatch"
VERDICT_STEP_NAME = "Release runner or enforce current-head CodeQL verdict"


def _run_verdict_read(
    tmp_path: Path, statuses: list[dict], *, second_page: list[dict] | None = None
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    """Execute the real one-shot status read and verdict enforcement blocks."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    dispatch_script = _extract_run_block(workflow_text, DISPATCH_STEP_NAME)
    verdict_script = _extract_run_block(workflow_text, VERDICT_STEP_NAME)

    head_sha = "b" * 40
    live_pr = {"head": {"sha": head_sha}, "state": "open"}

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'if [ "$#" = 2 ] && [ "$2" = "repos/ContextualWisdomLab/naruon/pulls/42" ]; then\n'
        "  printf '%s\\n' \"$FAKE_PULL_JSON\"\n"
        'elif [ "$#" = 4 ] && [ "$2" = --paginate ] && [ "$3" = --slurp ] &&\n'
        '  [ "$4" = "repos/ContextualWisdomLab/naruon/commits/${PR_HEAD_SHA}/statuses?per_page=100" ]; then\n'
        "  printf '%s\\n' \"$FAKE_STATUSES_JSON\"\n"
        "else\n"
        "  exit 1\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    output = tmp_path / "github-output"
    dispatch_env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(live_pr),
        "FAKE_STATUSES_JSON": json.dumps(
            [statuses] if second_page is None else [statuses, second_page]
        ),
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "PR_HEAD_SHA": head_sha,
        "LANGUAGE": "python",
        "BUILD_MODE": "none",
        "BASE_REF": "main",
        "BASE_SHA": "a" * 40,
        "HEAD_REF": "feature",
        "RUN_ATTEMPT": "2",
        "REQUIRED_RUN_ID": "42",
        "REQUIRED_JOB_ID": "43",
        "GITHUB_OUTPUT": str(output),
    }
    dispatch_result = subprocess.run(
        [bash], input=dispatch_script, text=True, capture_output=True, check=False,
        env=dispatch_env, timeout=60,
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    output_values = dict(
        line.split("=", 1) for line in output.read_text(encoding="utf-8").splitlines()
    )
    verdict_env = {
        **os.environ,
        "LANGUAGE": "python",
        "DISPATCH_OUTCOME": "success",
        "VERDICT_STATE": output_values["verdict"],
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


@pytest.mark.parametrize("state,exit_code", [("success", 0), ("failure", 1)])
def test_codeql_pr_reads_trusted_verdict_on_second_page(
    tmp_path: Path, state: str, exit_code: int
) -> None:
    """A full first page of forged successes cannot hide a later trusted verdict."""
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[
            {
                "context": "codeql-dispatch/python",
                "state": "success",
                "creator": {"login": "attacker"},
            }
            for _ in range(100)
        ],
        second_page=[
            {
                "context": "codeql-dispatch/python",
                "state": state,
                "creator": {"login": "opencode-agent[bot]"},
            }
        ],
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == exit_code, verdict_result.stderr
    if state == "success":
        assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout
    else:
        assert "did not pass (state=failure)" in verdict_result.stdout


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


def test_codeql_shard_releases_runner_and_dispatches_exact_wake_identity() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    shard = workflow.split("  analyze-head:\n", 1)[1]

    assert "while :; do" not in shard
    assert "poll_interval_seconds" not in shard
    assert "sleep " not in shard
    assert "job.check_run_id" in shard
    assert "required_run_id:$required_run_id" in shard
    assert "required_job_id:$required_job_id" in shard
    assert "required_language:$required_language" in shard
    assert "The dispatch workflow will rerun this exact failed CodeQL job" in shard
    assert "commits/${PR_HEAD_SHA}/statuses" in shard


def test_codeql_required_workflow_does_not_gain_actions_write() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    permissions = workflow.split("permissions:\n", 1)[1].split("\njobs:\n", 1)[0]
    shard_permissions = workflow.split("  analyze-head:\n", 1)[1].split(
        "    strategy:\n", 1
    )[0]

    assert "actions: write" not in permissions
    assert "actions: write" not in shard_permissions
