"""Structure and shell-syntax contract for the new codeql-scan-dispatch.yml handler.

ContextualWisdomLab/.github#1772 designs this file as the native
(non-required-workflow) half of the CodeQL dispatch architecture, and
ContextualWisdomLab/.github#1778 wires the required entrypoint to it. This
guards the handler's structure and shell syntax, mirroring the established pattern in
tests/test_opencode_workflow_shell_syntax.py and
tests/test_codeql_pr_workflow_contract.py.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import audit_central_required_workflows as ruleset_audit
from tests.test_opencode_workflow_shell_syntax import _extract_run_block
from tests.test_required_workflow_queue_contract import (
    workflow_level_cancels_in_progress,
    workflow_level_concurrency_group,
    workflow_step,
)


@pytest.mark.parametrize(
    ("gate", "upload", "expected_state"),
    [
        ("success", "failure", None),
        ("success", "skipped", None),
        ("success", "", None),
        ("success", "cancelled", None),
        ("success", "success", "success"),
        ("failure", "success", "failure"),
        ("skipped", "success", "error"),
    ],
)
def test_terminal_publication_requires_preserved_sarif(
    tmp_path: Path, gate: str, upload: str, expected_state: str | None
) -> None:
    """Execute production publication shell; missing artifacts cannot wake jobs."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _extract_run_block(workflow, "Publish CodeQL dispatch status")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    post_log = tmp_path / "status-posts"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'test "$1" = api && test "$2" = -X && test "$3" = POST\n'
        'test "$4" = "repos/ContextualWisdomLab/naruon/statuses/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"\n'
        'test "$5" = -f\n'
        'printf "%s\\n" "$6" >>"$FAKE_POST_LOG"\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        [shutil.which("bash") or "bash"], input=script, text=True,
        capture_output=True, check=False, timeout=30,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_POST_LOG": str(post_log),
            "GATE_OUTCOME": gate, "SARIF_UPLOAD_OUTCOME": upload,
            "TARGET_APP_STATUS_TOKEN": "fixture-token",
            "PR_REVIEW_MERGE_STATUS_TOKEN": "",
            "OPENCODE_APPROVE_STATUS_TOKEN": "", "GITHUB_STATUS_READ_TOKEN": "",
            "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
            "HEAD_SHA": "b" * 40, "LANGUAGE": "python",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "ContextualWisdomLab/.github", "GITHUB_RUN_ID": "99",
        },
    )
    # The actual workflow only admits wake when publication succeeded.
    wake = workflow_step(workflow, "Wake exact CodeQL required job")
    assert wake.split("        env:", 1)[0] == (
        "      - name: Wake exact CodeQL required job\n"
        "        if: >-\n"
        "          always()\n"
        "          && steps.publish_status.outcome == 'success'\n"
        "          && needs.validate-dispatch.outputs.target_repository != ''\n"
        "          && needs.validate-dispatch.outputs.pr_number != ''\n"
        "          && needs.validate-dispatch.outputs.head_sha != ''\n"
        "          && github.event.client_payload.required_run_id != ''\n"
        "          && github.event.client_payload.required_job_id != ''\n"
    )
    wake_posts = []
    if result.returncode == 0:
        wake_result, wake_log = _run_wake_step(tmp_path / "wake")
        assert wake_result.returncode == 0, wake_result.stderr
        wake_posts = wake_log.read_text(encoding="utf-8").splitlines()
    if expected_state is None:
        assert not post_log.exists(), result.stdout
        assert result.returncode == 1
        assert "SARIF evidence was not preserved" in result.stdout
        assert wake_posts == []
    else:
        assert result.returncode == 0, result.stderr
        assert post_log.read_text(encoding="utf-8").splitlines() == [f"state={expected_state}"]
        assert wake_posts == ["repos/ContextualWisdomLab/naruon/actions/jobs/43/rerun"]


def test_terminal_publication_binds_actual_upload_step_outcome() -> None:
    """The tested shell input must come from the existing artifact action."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    upload = workflow_step(workflow, "Preserve CodeQL SARIF evidence")
    assert upload.split("        uses:", 1)[0] == (
        "      - name: Preserve CodeQL SARIF evidence\n"
        "        id: sarif_upload\n"
        "        if: always() && hashFiles('codeql-results-dispatch/**/*.sarif') != ''\n"
    )
    assert "        uses: actions/upload-artifact@" in upload
    assert "          if-no-files-found: error" in upload.splitlines()
    publish = workflow_step(workflow, "Publish CodeQL dispatch status")
    env = publish.split("        env:\n", 1)[1].split("        run:", 1)[0]
    binding = [line for line in env.splitlines() if "SARIF_UPLOAD_OUTCOME" in line]
    assert binding == ["          SARIF_UPLOAD_OUTCOME: ${{ steps.sarif_upload.outcome }}"]

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-scan-dispatch.yml"
VALIDATE_STEP_NAME = "Bind workflow inputs to live organization pull request metadata"

RUN_BLOCK_STEP_NAMES = (
    "Exchange OpenCode app token for target repository metadata reads",
    "Bind workflow inputs to live organization pull request metadata",
    "Exchange OpenCode app token for target repository content reads",
    "Re-validate live pull request metadata before privileged scan",
    "Fetch the pinned CodeQL SARIF gate script",
    "Materialize pull request head for CodeQL scan",
    "Publish CodeQL dispatch status",
    "Wake exact CodeQL required job",
)


def test_codeql_scan_dispatch_run_blocks_are_valid_bash():
    """Every multi-line run: block in the new handler must be syntactically valid Bash."""
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


def test_codeql_scan_dispatch_workflow_structure():
    """The handler stays required-workflow-independent and reuses the shared SARIF gate."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "name: CodeQL Scan Dispatch" in workflow
    assert "types: [codeql-scan]" in workflow
    # No workflow_dispatch: test_no_central_workflow_exposes_branch_selected_manual_dispatch
    # (tests/test_required_workflow_queue_contract.py) forbids it on every
    # central workflow because it lets a caller pick an arbitrary ref to run
    # this token-minting, cross-repo-status-publishing workflow from.
    assert "workflow_dispatch:" not in workflow
    assert "validate-dispatch:" in workflow
    assert "  scan:" in workflow
    assert workflow.count("github/codeql-action/init@") == 1
    assert workflow.count("github/codeql-action/analyze@") == 1
    assert "scripts/ci/codeql_sarif_gate.py" in workflow
    assert 'context="codeql-dispatch/${LANGUAGE}"' in workflow
    assert "OPENCODE_REPOSITORY_DISPATCH_ACTOR" in workflow
    # Deliberately NOT vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS: that allowlist
    # scopes a gradual ~12-repo OpenCode review rollout, while ruleset
    # 18156473 covers ~ALL org repos except noema/.github/IRT-bibliography-set
    # -- reusing the narrower list would silently break CodeQL dispatch for
    # every repo not already on the OpenCode rollout list. (The name is
    # mentioned in an explanatory comment, which is fine -- only an actual
    # `vars.` reference would reintroduce the bug.)
    assert "vars.OPENCODE_REPOSITORY_DISPATCH_TARGETS" not in workflow
    # This file must never itself become subject to the required-workflow
    # codeql-action restriction: it must not be a pull_request-triggered file.
    assert "pull_request:" not in workflow
    assert "pull_request_target:" not in workflow


def test_codeql_scan_dispatch_keeps_current_head_language_shards_independent():
    """A current-head language scan cannot cancel its sibling language scans."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    group_value = workflow_level_concurrency_group(workflow)

    # The language segment is what keeps sibling language shards in separate groups, so it is
    # asserted on the group's own value: a comment naming it would otherwise satisfy the check
    # while the key had lost it, silently letting one language's scan cancel another's.
    assert "github.event.client_payload.target_repository" in group_value
    assert "github.event.client_payload.pr_number" in group_value
    assert "github.event.client_payload.required_language" in group_value
    # Same reasoning as the group above, applied to the flag: the substring form
    # is satisfied by a comment quoting it while the key beside it reads false.
    assert workflow_level_cancels_in_progress(workflow)


def _run_validate_step(tmp_path: Path, env_overrides: dict[str, str], pull_request: dict) -> subprocess.CompletedProcess[str]:
    """Execute the real validate-dispatch shell block against a fake `gh api`."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    script = _extract_run_block(workflow_text, VALIDATE_STEP_NAME)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'printf \'%s\\n\' "$FAKE_PULL_JSON"\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    output = tmp_path / "github-output"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull_request),
        "GITHUB_OUTPUT": str(output),
        "DISPATCH_ACTOR": "seonghobae",
        "DISPATCH_SENDER": "seonghobae",
        "ALLOWED_DISPATCH_ACTOR": "seonghobae",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "SUPPLIED_BASE_REF": "main",
        "SUPPLIED_BASE_SHA": "a" * 40,
        "SUPPLIED_HEAD_REF": "feature",
        "SUPPLIED_HEAD_SHA": "b" * 40,
        "SUPPLIED_MATRIX": json.dumps([{"language": "python", "build-mode": "none"}]),
        "SUPPLIED_REQUIRED_RUN_ID": "42",
        "SUPPLIED_REQUIRED_JOB_ID": "43",
        "SUPPLIED_REQUIRED_LANGUAGE": "python",
        **env_overrides,
    }
    result = subprocess.run([bash], input=script, text=True, capture_output=True, check=False, env=env)
    result.output_path = output  # type: ignore[attr-defined]
    return result


def _matching_pull_request() -> dict:
    """A live PR payload that matches the default supplied metadata in _run_validate_step."""
    return {
        "state": "open",
        "base": {"repo": {"full_name": "ContextualWisdomLab/naruon"}, "ref": "main", "sha": "a" * 40},
        "head": {"repo": {"full_name": "ContextualWisdomLab/naruon"}, "ref": "feature", "sha": "b" * 40},
    }


def test_codeql_scan_dispatch_validate_step_accepts_matching_live_metadata(tmp_path):
    """A dispatch whose metadata matches the live PR produces the expected GITHUB_OUTPUT."""
    result = _run_validate_step(tmp_path, {}, _matching_pull_request())

    assert result.returncode == 0, result.stderr
    output_text = result.output_path.read_text(encoding="utf-8")
    assert "target_repository=ContextualWisdomLab/naruon" in output_text
    assert "pr_number=42" in output_text
    assert "head_sha=" + "b" * 40 in output_text
    assert '[{"language":"python","build-mode":"none"}]' in output_text
    assert "required_run_id=42" in output_text
    assert "required_job_id=43" in output_text
    assert "required_language=python" in output_text


def test_codeql_scan_dispatch_validate_step_rejects_actor_mismatch(tmp_path):
    """A dispatch from an unauthorized actor is rejected before any live PR read."""
    result = _run_validate_step(tmp_path, {"DISPATCH_ACTOR": "someone-else"}, _matching_pull_request())

    assert result.returncode == 1
    assert "authorization rejected actor=" in result.stdout


def test_codeql_scan_dispatch_validate_step_accepts_any_listed_dispatcher(tmp_path):
    """ALLOWED_DISPATCH_ACTOR is a comma-separated allowlist shared by all three
    dispatch consumers; each listed identity passes when actor and sender both
    equal it, an unlisted one is rejected, and actor/sender that are two
    *different* listed identities are still rejected."""
    # _run_validate_step creates tmp_path/bin, so each invocation needs its
    # own directory.
    allowlist = "github-actions[bot], opencode-agent[bot]"
    for identity in ("github-actions[bot]", "opencode-agent[bot]"):
        result = _run_validate_step(
            tmp_path / identity.replace("[", "").replace("]", ""),
            {
                "ALLOWED_DISPATCH_ACTOR": allowlist,
                "DISPATCH_ACTOR": identity,
                "DISPATCH_SENDER": identity,
            },
            _matching_pull_request(),
        )
        assert result.returncode == 0, result.stderr
        assert f"Authorized repository_dispatch actor={identity}" in result.stdout

    unlisted = _run_validate_step(
        tmp_path / "unlisted",
        {
            "ALLOWED_DISPATCH_ACTOR": allowlist,
            "DISPATCH_ACTOR": "seonghobae",
            "DISPATCH_SENDER": "seonghobae",
        },
        _matching_pull_request(),
    )
    assert unlisted.returncode == 1
    assert "authorization rejected actor=seonghobae" in unlisted.stdout

    mismatched = _run_validate_step(
        tmp_path / "mismatched",
        {
            "ALLOWED_DISPATCH_ACTOR": allowlist,
            "DISPATCH_ACTOR": "opencode-agent[bot]",
            "DISPATCH_SENDER": "github-actions[bot]",
        },
        _matching_pull_request(),
    )
    assert mismatched.returncode == 1
    assert "authorization rejected actor=opencode-agent[bot]" in mismatched.stdout


def test_codeql_scan_dispatch_validate_step_accepts_any_org_repository(tmp_path):
    """Unlike opencode-review-dispatch.yml, any ContextualWisdomLab repo is accepted.

    CodeQL is meant to run for ~ALL org repos (ruleset 18156473's scope), not
    the curated ~12-repo OpenCode review rollout list -- a repo that would be
    rejected by that other allowlist must still be accepted here.
    """
    not_on_opencode_rollout_list = "ContextualWisdomLab/some-other-repo"
    pull_request = _matching_pull_request()
    pull_request["base"]["repo"]["full_name"] = not_on_opencode_rollout_list
    pull_request["head"]["repo"]["full_name"] = not_on_opencode_rollout_list

    result = _run_validate_step(
        tmp_path,
        {"TARGET_REPOSITORY": not_on_opencode_rollout_list},
        pull_request,
    )

    assert result.returncode == 0, result.stderr
    assert f"target_repository={not_on_opencode_rollout_list}" in result.output_path.read_text(encoding="utf-8")


def test_codeql_scan_dispatch_validate_step_rejects_non_org_target(tmp_path):
    """A dispatch targeting a repository outside ContextualWisdomLab is rejected."""
    result = _run_validate_step(
        tmp_path,
        {"TARGET_REPOSITORY": "some-other-org/repo"},
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "target outside ContextualWisdomLab" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_malformed_matrix(tmp_path):
    """A matrix entry missing a valid language/build-mode fails closed."""
    result = _run_validate_step(
        tmp_path,
        {"SUPPLIED_MATRIX": json.dumps([{"language": "python"}])},
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "matrix must contain exactly one valid language/build-mode shard" in result.stdout




def test_codeql_scan_dispatch_validate_step_rejects_stale_head_sha(tmp_path):
    """A dispatch whose supplied head SHA no longer matches the live PR head is rejected."""
    stale_pull_request = _matching_pull_request()
    stale_pull_request["head"]["sha"] = "c" * 40

    result = _run_validate_step(tmp_path, {}, stale_pull_request)

    assert result.returncode == 1
    assert "does not match the live pull request: head_sha" in result.stdout


def test_codeql_scan_dispatch_validate_step_rejects_closed_pull_request(tmp_path):
    """A dispatch targeting a pull request that closed before this run started is rejected."""
    closed_pull_request = _matching_pull_request()
    closed_pull_request["state"] = "closed"

    result = _run_validate_step(tmp_path, {}, closed_pull_request)

    assert result.returncode == 1
    assert "rejected closed, missing, cross-fork, or malformed live metadata" in result.stdout


def test_codeql_scan_dispatch_is_not_in_the_required_workflow_ruleset_scope():
    """Guard against accidentally wiring this handler in as its own required workflow.

    It must stay reachable only via repository_dispatch -- admitting it
    through the ruleset would immediately hit the same codeql-action
    admission restriction documented in
    docs/doctoring/codeql-pr-required-workflow-always-fails.md.
    """
    required_paths = set(ruleset_audit.REQUIRED_WORKFLOW_PATHS)

    assert ".github/workflows/codeql-pr.yml" in required_paths
    assert ".github/workflows/codeql-scan-dispatch.yml" not in required_paths


def test_dispatch_wakes_only_the_exact_failed_codeql_job() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    wake = workflow.split("      - name: Wake exact CodeQL required job\n", 1)[1].split(
        "\n\n      - name:", 1
    )[0]

    assert "steps.publish_status.outcome == 'success'" in wake
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in wake
    assert 'gh api "repos/${TARGET_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}"' in wake
    assert 'gh api "repos/${TARGET_REPOSITORY}/actions/jobs/${REQUIRED_JOB_ID}"' in wake
    assert 'select(.event == "pull_request")' in wake
    assert 'select(.path == ".github/workflows/codeql-pr.yml")' in wake
    assert "select(.head_sha == $head)" in wake
    assert "select(.run_id == $run_id)" in wake
    assert "select(.name == $name)" in wake
    assert 'select(.status == "completed" and .conclusion == "failure")' in wake
    assert 'actions/jobs/${REQUIRED_JOB_ID}/rerun' in wake
    assert "rerun-failed-jobs" not in wake
    assert "while " not in wake
    assert "sleep " not in wake


def test_dispatch_wake_has_only_trusted_actions_write_boundary() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    scan = workflow.split("  scan:\n", 1)[1]
    scan_permissions = scan.split("    strategy:\n", 1)[0]

    assert "actions: write" in scan_permissions
    assert "pull_request:" not in workflow
    assert "pull_request_target:" not in workflow
    assert "github.event.client_payload.required_run_id != ''" in scan
    assert "github.event.client_payload.required_job_id != ''" in scan


def _run_wake_step(
    tmp_path: Path,
    *,
    pull: dict | None = None,
    run: dict | None = None,
    job: dict | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Execute the exact wake block against fixture-backed GitHub API responses."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    head_sha = "b" * 40
    pull = pull or {"state": "open", "head": {"sha": head_sha}}
    run = run or {
        "id": 42,
        "event": "pull_request",
        "path": ".github/workflows/codeql-pr.yml",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "failure",
    }
    job = job or {
        "id": 43,
        "run_id": 42,
        "head_sha": head_sha,
        "name": "CodeQL compatibility analysis (python)",
        "status": "completed",
        "conclusion": "failure",
    }
    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), "Wake exact CodeQL required job"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    post_log = tmp_path / "posts"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'if [ "${2:-}" = "-X" ]; then\n'
        '  test "$3" = POST\n'
        '  printf \'%s\\n\' "$4" >>"$FAKE_POST_LOG"\n'
        "  exit 0\n"
        "fi\n"
        'case "$2" in\n'
        '  */pulls/*) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        '  */actions/runs/*) printf \'%s\\n\' "$FAKE_RUN_JSON" ;;\n'
        '  */actions/jobs/*) printf \'%s\\n\' "$FAKE_JOB_JSON" ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "FAKE_RUN_JSON": json.dumps(run),
        "FAKE_JOB_JSON": json.dumps(job),
        "FAKE_POST_LOG": str(post_log),
        "GH_TOKEN": "fake-token",
        "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "HEAD_SHA": head_sha,
        "REQUIRED_RUN_ID": "42",
        "REQUIRED_JOB_ID": "43",
        "REQUIRED_LANGUAGE": "python",
    }
    result = subprocess.run(
        [bash], input=script, text=True, capture_output=True, check=False, env=env
    )
    return result, post_log


def test_dispatch_wake_reruns_only_fixture_bound_exact_job(tmp_path: Path) -> None:
    result, post_log = _run_wake_step(tmp_path)

    assert result.returncode == 0, result.stderr
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/jobs/43/rerun"
    ]


def test_dispatch_wake_rejects_stale_head_and_closed_pr(tmp_path: Path) -> None:
    stale_result, stale_log = _run_wake_step(
        tmp_path / "stale", pull={"state": "open", "head": {"sha": "c" * 40}}
    )
    closed_result, closed_log = _run_wake_step(
        tmp_path / "closed", pull={"state": "closed", "head": {"sha": "b" * 40}}
    )

    assert stale_result.returncode == 1
    assert closed_result.returncode == 1
    assert not stale_log.exists()
    assert not closed_log.exists()


def test_dispatch_wake_rejects_ambiguous_or_nonfailed_job_identity(tmp_path: Path) -> None:
    wrong_job_result, wrong_job_log = _run_wake_step(
        tmp_path / "wrong-job",
        job={
            "id": 43,
            "run_id": 999,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed",
            "conclusion": "failure",
        },
    )
    successful_job_result, successful_job_log = _run_wake_step(
        tmp_path / "successful-job",
        job={
            "id": 43,
            "run_id": 42,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed",
            "conclusion": "success",
        },
    )

    assert wrong_job_result.returncode == 1
    assert successful_job_result.returncode == 1
    assert "missing or ambiguous exact run/job identity" in wrong_job_result.stdout
    assert not wrong_job_log.exists()
    assert not successful_job_log.exists()


def test_dispatch_wake_allows_parallel_language_rerun_on_same_exact_run(tmp_path: Path) -> None:
    """Another language may already have moved the shared run back to in_progress."""
    result, post_log = _run_wake_step(
        tmp_path,
        run={
            "id": 42,
            "event": "pull_request",
            "path": ".github/workflows/codeql-pr.yml",
            "head_sha": "b" * 40,
            "status": "in_progress",
            "conclusion": None,
        },
    )

    assert result.returncode == 0, result.stderr
    assert post_log.exists()


def test_codeql_scan_dispatch_serialises_the_matrix_payload() -> None:
    """The dispatched matrix reaches `env:` as JSON text, never as a raw sequence.

    `codeql-pr.yml` sends `client_payload.matrix` as an array. An `env:` value must be
    a scalar, so assigning the array directly makes GitHub reject that step when its
    `env:` is evaluated -- "A sequence was not expected" -- after the runner has been
    assigned and the earlier steps have already run. That shipped in #1776 and left this
    workflow at 0 successes across 136 attempts.

    No local tool catches it: `yaml.safe_load` parses the file and `actionlint` 1.7.12
    reports it clean, because it is an Actions template rule rather than YAML syntax.
    Only GitHub's own validator rejects it, so this string contract is the only guard
    that runs before a dispatch does. The validate step consumes the value through
    `jq`, so JSON text is what it already expects.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert (
        "SUPPLIED_MATRIX: ${{ toJSON(github.event.client_payload.matrix) }}" in workflow
    ), "SUPPLIED_MATRIX must be serialised with toJSON(); a bare array breaks template validation"
    assert (
        "SUPPLIED_MATRIX: ${{ github.event.client_payload.matrix" not in workflow
    ), "SUPPLIED_MATRIX must not assign the raw client_payload array to env:"
