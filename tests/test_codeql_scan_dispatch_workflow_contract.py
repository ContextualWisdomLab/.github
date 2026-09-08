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
        'printf "%s\\n" "$6" >>"$FAKE_POST_LOG"\n'
        "printf '%s\\n' '{\"creator\":{\"login\":\"opencode-agent[bot]\"}}'\n",
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
            "BASE_SHA": "a" * 40, "HEAD_SHA": "b" * 40, "LANGUAGE": "python",
            "GITHUB_SERVER_URL": "https://github.com",
                "GITHUB_REPOSITORY": "ContextualWisdomLab/.github", "GITHUB_RUN_ID": "99",
                "REQUIRED_RUN_ID": "42",
                "PRODUCER_SOURCE_SHA": "c" * 40,
        },
    )
    # Settlement is a separate non-matrix job and independently authenticates
    # either a receipt or exact scan-plus-artifact evidence.
    wake = workflow_step(workflow, "Settle exact CodeQL required run")
    assert wake.split("        env:", 1)[0] == (
        "      - name: Settle exact CodeQL required run\n"
        "        if: >-\n"
        "          always()\n"
        "          && needs.validate-dispatch.outputs.target_repository != ''\n"
        "          && needs.validate-dispatch.outputs.pr_number != ''\n"
        "          && needs.validate-dispatch.outputs.head_sha != ''\n"
        "          && needs.validate-dispatch.outputs.required_run_id != ''\n"
        "          && needs.validate-dispatch.outputs.required_jobs != ''\n"
    )
    if expected_state is None:
        assert not post_log.exists(), result.stdout
        assert result.returncode == 1
        assert "SARIF evidence was not preserved" in result.stdout
    else:
        assert result.returncode == 0, result.stderr
        assert post_log.read_text(encoding="utf-8").splitlines() == [f"state={expected_state}"]


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


def test_self_repository_app_403_falls_back_to_the_exact_workflow_token(
    tmp_path: Path,
) -> None:
    """Reproduce the live App 403 and prove the fallback publisher is explicit."""
    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), "Publish CodeQL dispatch status"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "calls"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'printf "%s\\n" "$GH_TOKEN" >>"$FAKE_CALL_LOG"\n'
        'if [ "$GH_TOKEN" = app-token ]; then\n'
        '  echo "gh: Resource not accessible by integration (HTTP 403)" >&2\n'
        "  exit 1\n"
        "fi\n"
        'test "$GH_TOKEN" = github-token\n'
        'test "$1" = api && test "$2" = -X && test "$3" = POST\n'
        'test "$4" = "repos/ContextualWisdomLab/.github/statuses/${HEAD_SHA}"\n'
        "printf '%s\\n' '{\"creator\":{\"login\":\"github-actions[bot]\"}}'\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        [shutil.which("bash") or "bash"], input=script, text=True,
        capture_output=True, check=False, timeout=30,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_CALL_LOG": str(call_log),
            "GATE_OUTCOME": "success", "SARIF_UPLOAD_OUTCOME": "success",
            "TARGET_APP_STATUS_TOKEN": "app-token",
            "PR_REVIEW_MERGE_STATUS_TOKEN": "",
            "OPENCODE_APPROVE_STATUS_TOKEN": "",
            "GITHUB_STATUS_READ_TOKEN": "github-token",
            "TARGET_REPOSITORY": "ContextualWisdomLab/.github",
            "BASE_SHA": "a" * 40, "HEAD_SHA": "b" * 40,
            "LANGUAGE": "python", "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "ContextualWisdomLab/.github",
                "GITHUB_RUN_ID": "123",
                "REQUIRED_RUN_ID": "42",
                "PRODUCER_SOURCE_SHA": "c" * 40,
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "app-token", "github-token",
    ]
    assert "Resource not accessible by integration (HTTP 403)" in result.stdout
    assert "using github-token" in result.stdout


def test_status_post_with_unexpected_creator_falls_through_to_trusted_publisher(
    tmp_path: Path,
) -> None:
    """HTTP success is not publication until the response creator is trusted."""
    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), "Publish CodeQL dispatch status"
    )
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "calls"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        'printf "%s\n" "$GH_TOKEN" >>"$FAKE_CALL_LOG"\n'
        'test "$1" = api && test "$2" = -X && test "$3" = POST\n'
        'if [ "$GH_TOKEN" = app-token ]; then\n'
        '  printf "%s\n" \'{"creator":{"login":"unexpected-user"}}\'\n'
        "  exit 0\n"
        "fi\n"
        'test "$GH_TOKEN" = github-token\n'
        'printf "%s\n" \'{"creator":{"login":"github-actions[bot]"}}\'\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        [shutil.which("bash") or "bash"],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_CALL_LOG": str(call_log),
            "GATE_OUTCOME": "success",
            "SARIF_UPLOAD_OUTCOME": "success",
            "TARGET_APP_STATUS_TOKEN": "app-token",
            "PR_REVIEW_MERGE_STATUS_TOKEN": "",
            "OPENCODE_APPROVE_STATUS_TOKEN": "",
            "GITHUB_STATUS_READ_TOKEN": "github-token",
            "TARGET_REPOSITORY": "ContextualWisdomLab/.github",
            "BASE_SHA": "a" * 40,
            "HEAD_SHA": "b" * 40,
            "LANGUAGE": "python",
            "GITHUB_SERVER_URL": "https://github.com",
            "GITHUB_REPOSITORY": "ContextualWisdomLab/.github",
                "GITHUB_RUN_ID": "123",
                "REQUIRED_RUN_ID": "42",
                "PRODUCER_SOURCE_SHA": "c" * 40,
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "app-token",
        "github-token",
    ]
    assert "unexpected creator" in result.stdout
    assert "using github-token" in result.stdout

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
    "Settle exact CodeQL required run",
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
    assert 'context="codeql-dispatch/${LANGUAGE}/${BASE_SHA}"' in workflow
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


def test_codeql_scan_dispatch_publishes_base_bound_workflow_receipt() -> None:
    """Terminal status carries the base, head, language, and producer identity."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "BASE_SHA: ${{ needs.validate-dispatch.outputs.base_sha }}" in workflow
    assert 'context="codeql-dispatch/${LANGUAGE}/${BASE_SHA}"' in workflow
    assert (
        'receipt_description="cwl1;h=${HEAD_SHA};w=codeql-scan-dispatch;r=${REQUIRED_RUN_ID};s=${PRODUCER_SOURCE_SHA}"'
        in workflow
    )
    assert '-f description="$receipt_description"' in workflow
    assert (
        '-f target_url="${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}/actions/runs/'
        '${GITHUB_RUN_ID}"' in workflow
    )


def test_codeql_scan_dispatch_keeps_current_head_language_shards_independent():
    """Sibling languages stay independent as jobs in one run, not as separate runs.

    The 60-job ceiling was one queued handler run per language. Putting
    ``required_language`` in the concurrency group was the 2026-09-05
    workaround after contextual-orchestrator#1049 / run 33938784437 cancelled
    sibling scans. Independence now comes from ``strategy.fail-fast: false``
    on this run's language matrix, so the group can be
    ``{workflow}-{repository}-{PR}`` and ``cancel-in-progress: true`` only
    drops a superseded HEAD of the same pull request.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    group_value = workflow_level_concurrency_group(workflow)
    header = workflow.split("\non:", 1)[0]
    scan = workflow.split("  scan:\n", 1)[1]
    strategy = scan.split("    strategy:\n", 1)[1].split("    steps:\n", 1)[0]

    assert "github.event.client_payload.target_repository" in group_value
    assert "github.event.client_payload.pr_number" in group_value
    assert "github.event.client_payload.required_language" not in group_value
    assert "unknown-language" not in group_value
    assert "required_language" not in header
    assert "fail-fast: false" in strategy
    assert "include: ${{ fromJSON(needs.validate-dispatch.outputs.matrix) }}" in strategy
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
        'case "$2" in\n'
        '  repos/ContextualWisdomLab/.github/compare/*) printf \'%s\\n\' "$FAKE_SOURCE_COMPARE_JSON" ;;\n'
        '  *) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        'esac\n',
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
        "SUPPLIED_REQUIRED_JOBS": json.dumps([{"language": "python", "job_id": 43}]),
        "SUPPLIED_RERUN_MODE": "failed",
        "SUPPLIED_PRODUCER_SOURCE_SHA": "c" * 40,
        "WORKFLOW_SOURCE_SHA": "c" * 40,
        "FAKE_SOURCE_COMPARE_JSON": json.dumps(
            {
                "status": "identical",
                "base_commit": {"sha": "c" * 40},
                "merge_base_commit": {"sha": "c" * 40},
            }
        ),
        "SUPPLIED_REQUIRED_JOB_ID": "",
        "SUPPLIED_REQUIRED_LANGUAGE": "",
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
    assert "rerun_mode=failed" in output_text
    assert "producer_source_sha=" + "c" * 40 in output_text
    assert '"job_id":43' in output_text.replace(" ", "")
    assert "required_job_id=" not in output_text
    assert "required_language=" not in output_text


@pytest.mark.parametrize("rerun_mode", ["", "failure", "ALL", "all-jobs"])
def test_codeql_scan_dispatch_validate_step_rejects_invalid_rerun_mode(
    tmp_path: Path, rerun_mode: str,
) -> None:
    """Only the bounded failed-job and whole-attempt wake modes are accepted."""
    result = _run_validate_step(
        tmp_path,
        {"SUPPLIED_RERUN_MODE": rerun_mode},
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "rerun mode" in result.stdout.lower()


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
    """Empty, invalid, or job-map-mismatched matrices fail closed; a multi-language payload is valid."""
    missing_build_mode = _run_validate_step(
        tmp_path / "missing-build-mode",
        {"SUPPLIED_MATRIX": json.dumps([{"language": "python"}])},
        _matching_pull_request(),
    )
    empty_matrix = _run_validate_step(
        tmp_path / "empty",
        {
            "SUPPLIED_MATRIX": "[]",
            "SUPPLIED_REQUIRED_JOBS": "[]",
        },
        _matching_pull_request(),
    )
    invalid_language = _run_validate_step(
        tmp_path / "invalid-language",
        {
            "SUPPLIED_MATRIX": json.dumps([{"language": "PYTHON", "build-mode": "none"}]),
            "SUPPLIED_REQUIRED_JOBS": json.dumps([{"language": "PYTHON", "job_id": 43}]),
        },
        _matching_pull_request(),
    )
    mismatched_jobs = _run_validate_step(
        tmp_path / "mismatched-jobs",
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "actions", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps([{"language": "python", "job_id": 43}]),
        },
        _matching_pull_request(),
    )

    assert missing_build_mode.returncode == 1
    assert empty_matrix.returncode == 1
    assert invalid_language.returncode == 1
    assert mismatched_jobs.returncode == 1
    assert "at least one valid language/build-mode shard" in missing_build_mode.stdout
    assert "at least one valid language/build-mode shard" in empty_matrix.stdout
    assert "at least one valid language/build-mode shard" in invalid_language.stdout
    assert "is duplicate or does not cover every dispatched language" in mismatched_jobs.stdout


def test_codeql_scan_dispatch_validate_step_accepts_multi_language_payload(tmp_path):
    """One dispatch may carry every remaining language for the current head."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "javascript-typescript", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps(
                [
                    {"language": "javascript-typescript", "job_id": "55"},
                    {"language": "python", "job_id": 43},
                ]
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    output_text = result.output_path.read_text(encoding="utf-8")
    assert "javascript-typescript" in output_text
    assert '"job_id":55' in output_text.replace(" ", "")
    assert '"job_id":43' in output_text.replace(" ", "")


def test_codeql_scan_dispatch_accepts_pending_subset_with_complete_failed_job_map(
    tmp_path,
):
    """Pending scan languages may be a subset of run-wide failed-job identity."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_MATRIX": json.dumps(
                [{"language": "actions", "build-mode": "none"}]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps(
                [
                    {"language": "python", "job_id": 43},
                    {"language": "actions", "job_id": 55},
                ]
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    compact = result.output_path.read_text(encoding="utf-8").replace(" ", "")
    assert '"language":"python"' in compact
    assert '"job_id":43' in compact
    assert '"language":"actions"' in compact
    assert '"job_id":55' in compact


@pytest.mark.parametrize(
    ("supplied", "runtime"),
    [("", "c" * 40), ("not-a-sha", "c" * 40), ("c" * 40, "d" * 40)],
)
def test_codeql_scan_dispatch_rejects_missing_or_wrong_producer_source(
    tmp_path: Path, supplied: str, runtime: str,
) -> None:
    """Payload source must equal the immutable handler workflow source."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_PRODUCER_SOURCE_SHA": supplied,
            "WORKFLOW_SOURCE_SHA": runtime,
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "producer source" in result.stdout.lower()


def test_codeql_scan_dispatch_accepts_ancestor_producer_source(
    tmp_path: Path,
) -> None:
    """A protected producer source remains compatible after handler main advances."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_PRODUCER_SOURCE_SHA": "c" * 40,
            "WORKFLOW_SOURCE_SHA": "d" * 40,
            "FAKE_SOURCE_COMPARE_JSON": json.dumps(
                {
                    "status": "ahead",
                    "ahead_by": 1,
                    "behind_by": 0,
                    "base_commit": {"sha": "c" * 40},
                    "merge_base_commit": {"sha": "c" * 40},
                }
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "producer_source_sha=" + "c" * 40 in result.output_path.read_text(
        encoding="utf-8"
    )


def test_codeql_scan_dispatch_rejects_divergent_producer_source(
    tmp_path: Path,
) -> None:
    """A source outside the immutable handler ancestry fails closed."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_PRODUCER_SOURCE_SHA": "c" * 40,
            "WORKFLOW_SOURCE_SHA": "d" * 40,
            "FAKE_SOURCE_COMPARE_JSON": json.dumps(
                {
                    "status": "diverged",
                    "ahead_by": 1,
                    "behind_by": 1,
                    "base_commit": {"sha": "c" * 40},
                    "merge_base_commit": {"sha": "e" * 40},
                }
            ),
        },
        _matching_pull_request(),
    )

    assert result.returncode == 1
    assert "producer source" in result.stdout.lower()


def test_codeql_scan_dispatch_validate_step_accepts_legacy_single_language_payload(tmp_path):
    """A queued pre-cutover payload still validates after required_jobs became mandatory.

    repository_dispatch always runs the default-branch file. Payloads that
    lined up before #2008 carry required_language + required_job_id and a
    one-shard matrix, with required_jobs absent (JSON null) or empty. Those
    fields synthesize required_jobs=[{language, job_id}] and must be accepted.
    """
    for empty_jobs, case_name in (("null", "missing"), ("[]", "empty-array")):
        result = _run_validate_step(
            tmp_path / case_name,
            {
                "SUPPLIED_REQUIRED_JOBS": empty_jobs,
                "SUPPLIED_REQUIRED_LANGUAGE": "python",
                "SUPPLIED_REQUIRED_JOB_ID": "43",
            },
            _matching_pull_request(),
        )

        assert result.returncode == 0, result.stderr + result.stdout
        output_text = result.output_path.read_text(encoding="utf-8")
        compact = output_text.replace(" ", "")
        assert '"language":"python"' in compact
        assert '"job_id":43' in compact
        assert "required_job_id=" not in output_text
        assert "required_language=" not in output_text


def test_codeql_scan_dispatch_validate_step_ignores_legacy_fields_when_required_jobs_present(
    tmp_path,
):
    """A current required_jobs array wins; leftover scalar fields are ignored."""
    result = _run_validate_step(
        tmp_path,
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "javascript-typescript", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": json.dumps(
                [
                    {"language": "javascript-typescript", "job_id": "55"},
                    {"language": "python", "job_id": 43},
                ]
            ),
            "SUPPLIED_REQUIRED_LANGUAGE": "actions",
            "SUPPLIED_REQUIRED_JOB_ID": "999",
        },
        _matching_pull_request(),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    compact = result.output_path.read_text(encoding="utf-8").replace(" ", "")
    assert '"job_id":55' in compact
    assert '"job_id":43' in compact
    assert '"job_id":999' not in compact
    assert "actions" not in compact


def test_codeql_scan_dispatch_validate_step_rejects_unusable_legacy_payload(tmp_path):
    """Empty required_jobs still fail closed when the scalar identity cannot be synthesized."""
    missing_both = _run_validate_step(
        tmp_path / "missing-both",
        {"SUPPLIED_REQUIRED_JOBS": "null"},
        _matching_pull_request(),
    )
    language_mismatch = _run_validate_step(
        tmp_path / "language-mismatch",
        {
            "SUPPLIED_REQUIRED_JOBS": "[]",
            "SUPPLIED_REQUIRED_LANGUAGE": "javascript-typescript",
            "SUPPLIED_REQUIRED_JOB_ID": "43",
        },
        _matching_pull_request(),
    )
    multi_language_legacy = _run_validate_step(
        tmp_path / "multi-language-legacy",
        {
            "SUPPLIED_MATRIX": json.dumps(
                [
                    {"language": "python", "build-mode": "none"},
                    {"language": "javascript-typescript", "build-mode": "none"},
                ]
            ),
            "SUPPLIED_REQUIRED_JOBS": "null",
            "SUPPLIED_REQUIRED_LANGUAGE": "python",
            "SUPPLIED_REQUIRED_JOB_ID": "43",
        },
        _matching_pull_request(),
    )
    invalid_job_id = _run_validate_step(
        tmp_path / "invalid-job-id",
        {
            "SUPPLIED_REQUIRED_JOBS": "null",
            "SUPPLIED_REQUIRED_LANGUAGE": "python",
            "SUPPLIED_REQUIRED_JOB_ID": "0",
        },
        _matching_pull_request(),
    )

    assert missing_both.returncode == 1
    assert language_mismatch.returncode == 1
    assert multi_language_legacy.returncode == 1
    assert invalid_job_id.returncode == 1
    assert "is duplicate or does not cover every dispatched language" in missing_both.stdout
    assert "is duplicate or does not cover every dispatched language" in language_mismatch.stdout
    assert "is duplicate or does not cover every dispatched language" in multi_language_legacy.stdout
    assert "is duplicate or does not cover every dispatched language" in invalid_job_id.stdout




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


def test_codeql_scan_dispatch_run_name_binds_base_and_required_run() -> None:
    """Native run identity cannot be shared across base or required-run contexts."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    header = workflow.split("\non:", 1)[0]

    assert "github.event.client_payload.pr_base_sha" in header
    assert "github.event.client_payload.required_run_id" in header


def test_dispatch_settles_only_the_exact_failed_codeql_run() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    wake = workflow.split("      - name: Settle exact CodeQL required run\n", 1)[1].split(
        "\n\n      - name:", 1
    )[0]

    assert "steps.publish_status.outcome" not in wake
    assert 'gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"' in wake
    assert 'gh api "repos/${TARGET_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}"' in wake
    assert 'gh api "repos/${TARGET_REPOSITORY}/actions/jobs/${required_job_id}"' in wake
    assert "commits/${HEAD_SHA}/statuses?per_page=100" in wake
    assert 'select(.event == "pull_request")' in wake
    assert 'select(.path == ".github/workflows/codeql-pr.yml")' in wake
    assert "select(.head_sha == $head)" in wake
    assert "select(.run_id == $run_id)" in wake
    assert "select(.name == $name)" in wake
    assert 'select(.status == "completed" and .conclusion == "failure")' in wake
    assert 'wake_endpoint="rerun-failed-jobs"' in wake
    assert 'actions/runs/${REQUIRED_RUN_ID}/${wake_endpoint}' in wake
    assert 'actions/jobs/${REQUIRED_JOB_ID}/rerun' not in wake
    assert "sleep " not in wake


def test_dispatch_wake_has_only_trusted_actions_write_boundary() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    scan = workflow.split("  scan:\n", 1)[1].split("  wake-required:\n", 1)[0]
    scan_permissions = scan.split("    strategy:\n", 1)[0]
    wake = workflow.split("  wake-required:\n", 1)[1]

    assert "actions: write" not in scan_permissions
    assert "actions: read" in scan_permissions
    assert "needs: [validate-dispatch, scan]" in wake
    assert "actions: write" in wake.split("    steps:\n", 1)[0]
    assert "matrix:" not in wake.split("    steps:\n", 1)[0]
    assert "steps.publish_status.outcome" not in wake
    assert "pull_request:" not in workflow
    assert "pull_request_target:" not in workflow
    assert "needs.validate-dispatch.outputs.required_run_id != ''" in wake
    assert "needs.validate-dispatch.outputs.required_jobs != ''" in wake
    assert "github.event.client_payload.required_job_id" not in scan


def _run_wake_step(
    tmp_path: Path,
    *,
    pull: dict | None = None,
    run: dict | None = None,
    jobs: list[dict] | None = None,
    statuses: list[dict] | None = None,
    post_failure: bool = False,
    settled_jobs: list[dict] | None = None,
    target_repository: str = "ContextualWisdomLab/naruon",
    producer_jobs: dict | list[dict] | None = None,
    producer_artifacts: dict | list[dict] | None = None,
    predecessor_run: dict | None = None,
    predecessor_jobs: dict | list[dict] | None = None,
    predecessor_artifacts: dict | list[dict] | None = None,
    handler_source_sha: str | None = None,
    source_compare: dict | None = None,
    base_compare: dict | None = None,
    rerun_mode: str = "failed",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Execute exact-run settlement against fixture-backed GitHub responses."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    head_sha = "b" * 40
    base_sha = "a" * 40
    handler_source_sha = handler_source_sha or "c" * 40
    pull = pull or {
        "state": "open", "head": {"sha": head_sha},
        "base": {"sha": base_sha, "ref": "main"},
    }
    run = run or {
        "id": 42,
        "event": "pull_request",
        "path": ".github/workflows/codeql-pr.yml",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "failure",
    }
    jobs = jobs or [
        {
            "id": 43, "run_id": 42, "run_attempt": 1, "head_sha": head_sha,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed", "conclusion": "failure",
        },
        {
            "id": 44, "run_id": 42, "run_attempt": 1, "head_sha": head_sha,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "completed", "conclusion": "failure",
        },
    ]
    statuses = statuses if statuses is not None else [
        {
            "context": f"codeql-dispatch/python/{base_sha}",
            "description": (
                f"cwl1;h={head_sha};w=codeql-scan-dispatch;r=42;"
                f"s={'c' * 40}"
            ),
            "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/100",
            "state": "success", "creator": {"login": "opencode-agent[bot]"},
        },
        {
            "context": f"codeql-dispatch/actions/{base_sha}",
            "description": (
                f"cwl1;h={head_sha};w=codeql-scan-dispatch;r=42;"
                f"s={'c' * 40}"
            ),
            "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/100",
            "state": "success", "creator": {"login": "opencode-agent[bot]"},
        },
    ]
    settled_jobs = settled_jobs if settled_jobs is not None else jobs
    producer_run = {
        "id": 100,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_branch": "main",
        "head_sha": handler_source_sha,
        "display_title": (
            f"CodeQL Scan Dispatch {target_repository}#42@{head_sha}/{base_sha}/42/"
            f"{'c' * 40}"
        ),
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
    }
    predecessor_run = predecessor_run or {
        **producer_run,
        "id": 99,
    }
    predecessor_jobs = predecessor_jobs if predecessor_jobs is not None else {
        "jobs": []
    }
    predecessor_artifacts = (
        predecessor_artifacts if predecessor_artifacts is not None
        else {"artifacts": []}
    )
    producer_jobs = producer_jobs if producer_jobs is not None else {
        "jobs": [
            {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
            *[
                {
                    "name": f"CodeQL dispatch scan ({language})",
                    "status": "completed",
                    "conclusion": "failure",
                    "run_attempt": 1,
                    "steps": [
                        {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                        {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
                        {"name": "Publish CodeQL dispatch status", "conclusion": "failure"},
                    ],
                }
                for language in ("python", "actions")
            ],
        ]
    }
    producer_artifacts = producer_artifacts if producer_artifacts is not None else {
        "artifacts": [
            {"name": f"codeql-dispatch-{language}-100-1", "expired": False}
            for language in ("python", "actions")
        ]
    }
    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), "Settle exact CodeQL required run"
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
        '  if [ "$FAKE_POST_FAILURE" = 1 ]; then printf \'%s\\n\' "gh: workflow run already running (HTTP 403)" >&2; exit 1; fi\n'
        "  exit 0\n"
        "fi\n"
        'if [ "${2:-}" = "--paginate" ] && [ "${3:-}" = "--slurp" ]; then\n'
        '  case "${4:-}" in\n'
        '    */statuses*) printf \'%s\\n\' "$FAKE_STATUSES_JSON" ;;\n'
        '    */actions/runs/100/jobs*) printf \'%s\\n\' "$FAKE_PRODUCER_JOBS_JSON" ;;\n'
        '    */actions/runs/100/artifacts*) printf \'%s\\n\' "$FAKE_PRODUCER_ARTIFACTS_JSON" ;;\n'
        '    */actions/runs/99/jobs*) printf \'%s\\n\' "$FAKE_PREDECESSOR_JOBS_JSON" ;;\n'
        '    */actions/runs/99/artifacts*) printf \'%s\\n\' "$FAKE_PREDECESSOR_ARTIFACTS_JSON" ;;\n'
        '    *) exit 1 ;;\n'
        '  esac\n'
        'elif [ "${2:-}" = "--paginate" ]; then\n'
        '  if [[ "${3:-}" == *"filter=all"* ]]; then body=$FAKE_ALL_JOBS_JSON; else body=$FAKE_LATEST_JOBS_JSON; fi\n'
        '  printf \'%s\\n\' "$body" | jq -c \'.jobs[]\'\n'
        'else case "$2" in\n'
        '  */pulls/*) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        '  */compare/*) if [[ "$2" == "repos/${TARGET_REPOSITORY}/compare/${BASE_SHA}..."* ]]; then printf \'%s\\n\' "$FAKE_BASE_COMPARE_JSON"; else printf \'%s\\n\' "$FAKE_SOURCE_COMPARE_JSON"; fi ;;\n'
        '  repos/ContextualWisdomLab/.github/actions/runs/100) printf \'%s\\n\' "$FAKE_PRODUCER_RUN_JSON" ;;\n'
        '  repos/ContextualWisdomLab/.github/actions/runs/99) printf \'%s\\n\' "$FAKE_PREDECESSOR_RUN_JSON" ;;\n'
        '  */actions/runs/*) printf \'%s\\n\' "$FAKE_RUN_JSON" ;;\n'
        '  */actions/jobs/43) printf \'%s\\n\' "$FAKE_JOB_43_JSON" ;;\n'
        '  */actions/jobs/44) printf \'%s\\n\' "$FAKE_JOB_44_JSON" ;;\n'
        "  *) exit 1 ;;\n"
        "esac; fi\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "FAKE_RUN_JSON": json.dumps(run),
        "FAKE_PRODUCER_RUN_JSON": json.dumps(producer_run),
        "FAKE_PREDECESSOR_RUN_JSON": json.dumps(predecessor_run),
        "FAKE_PRODUCER_JOBS_JSON": json.dumps(
            producer_jobs if isinstance(producer_jobs, list) else [producer_jobs]
        ),
        "FAKE_PRODUCER_ARTIFACTS_JSON": json.dumps(
            producer_artifacts if isinstance(producer_artifacts, list)
            else [producer_artifacts]
        ),
        "FAKE_PREDECESSOR_JOBS_JSON": json.dumps(
            predecessor_jobs if isinstance(predecessor_jobs, list)
            else [predecessor_jobs]
        ),
        "FAKE_PREDECESSOR_ARTIFACTS_JSON": json.dumps(
            predecessor_artifacts if isinstance(predecessor_artifacts, list)
            else [predecessor_artifacts]
        ),
        "FAKE_SOURCE_COMPARE_JSON": json.dumps(
            source_compare
            or {
                "status": "identical",
                "base_commit": {"sha": "c" * 40},
                "merge_base_commit": {"sha": "c" * 40},
            }
        ),
        "FAKE_BASE_COMPARE_JSON": json.dumps(
            base_compare
            or {
                "status": "identical",
                "ahead_by": 0,
                "behind_by": 0,
                "base_commit": {"sha": base_sha},
                "merge_base_commit": {"sha": base_sha},
            }
        ),
        "FAKE_JOB_43_JSON": json.dumps(next(job for job in jobs if job["id"] == 43)),
        "FAKE_JOB_44_JSON": json.dumps(next(job for job in jobs if job["id"] == 44)),
        "FAKE_STATUSES_JSON": json.dumps([statuses]),
        "FAKE_LATEST_JOBS_JSON": json.dumps({"jobs": jobs}),
        "FAKE_ALL_JOBS_JSON": json.dumps({"jobs": settled_jobs}),
        "FAKE_POST_FAILURE": "1" if post_failure else "0",
        "FAKE_POST_LOG": str(post_log),
        "GH_TOKEN": "fake-token",
        "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
        "TARGET_REPOSITORY": target_repository,
        "PR_NUMBER": "42",
        "HEAD_SHA": head_sha,
        "BASE_REF": "main",
        "BASE_SHA": base_sha,
        "REQUIRED_RUN_ID": "42",
        "REQUIRED_JOBS": json.dumps(
            [
                {"language": "python", "job_id": 43},
                {"language": "actions", "job_id": 44},
            ]
        ),
        "RERUN_MODE": rerun_mode,
        "PRODUCER_RUN_ID": "100",
        "PRODUCER_SOURCE_SHA": "c" * 40,
        "HANDLER_REPOSITORY": "ContextualWisdomLab/.github",
    }
    result = subprocess.run(
        [bash], input=script, text=True, capture_output=True, check=False, env=env
    )
    return result, post_log


def test_dispatch_settlement_reruns_failed_jobs_only_after_all_receipts(
    tmp_path: Path,
) -> None:
    result, post_log = _run_wake_step(tmp_path)

    assert result.returncode == 0, result.stderr
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs"
    ]


def test_dispatch_settlement_reuses_authenticated_predecessor_receipt(
    tmp_path: Path,
) -> None:
    """Mixed matrices may combine a prior receipt with current direct evidence."""
    head_sha = "b" * 40
    base_sha = "a" * 40
    source_sha = "c" * 40
    statuses = [
        {
            "context": f"codeql-dispatch/python/{base_sha}",
            "description": (
                f"cwl1;h={head_sha};w=codeql-scan-dispatch;r=42;s={source_sha}"
            ),
            "target_url": (
                "https://github.com/ContextualWisdomLab/.github/actions/runs/99"
            ),
            "state": "success",
            "creator": {"login": "opencode-agent[bot]"},
        }
    ]
    current_jobs = {
        "jobs": [
            {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
            {
                "name": "CodeQL dispatch scan (actions)",
                "status": "completed",
                "conclusion": "failure",
                "run_attempt": 1,
                "steps": [
                    {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "failure"},
                    {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
                ],
            },
        ]
    }
    predecessor_jobs = {
        "jobs": [
            {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
            {
                "name": "CodeQL dispatch scan (python)",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
                "steps": [
                    {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                    {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
                ],
            },
        ]
    }

    result, post_log = _run_wake_step(
        tmp_path,
        statuses=statuses,
        producer_jobs=current_jobs,
        producer_artifacts={
            "artifacts": [
                {"name": "codeql-dispatch-actions-100-1", "expired": False}
            ]
        },
        predecessor_jobs=predecessor_jobs,
        predecessor_artifacts={
            "artifacts": [
                {"name": "codeql-dispatch-python-99-1", "expired": False}
            ]
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs"
    ]


@pytest.mark.parametrize(
    ("receipt_state", "gate_steps"),
    [
        ("success", []),
        (
            "success",
            [
                {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
            ],
        ),
        (
            "success",
            [{"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "failure"}],
        ),
        (
            "failure",
            [{"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"}],
        ),
        (
            "error",
            [{"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "failure"}],
        ),
    ],
)
def test_dispatch_settlement_rejects_receipt_without_exact_matching_gate(
    tmp_path: Path, receipt_state: str, gate_steps: list[dict[str, str]],
) -> None:
    """A predecessor receipt must bind one gate outcome to its published state."""
    head_sha = "b" * 40
    base_sha = "a" * 40
    source_sha = "c" * 40
    statuses = [{
        "context": f"codeql-dispatch/python/{base_sha}",
        "description": f"cwl1;h={head_sha};w=codeql-scan-dispatch;r=42;s={source_sha}",
        "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/99",
        "state": receipt_state,
        "creator": {"login": "opencode-agent[bot]"},
    }]
    predecessor_jobs = {"jobs": [
        {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
        {
            "name": "CodeQL dispatch scan (python)",
            "status": "completed",
            "conclusion": "success" if receipt_state == "success" else "failure",
            "run_attempt": 1,
            "steps": [
                *gate_steps,
                {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
            ],
        },
    ]}
    current_jobs = {"jobs": [
        {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
        {
            "name": "CodeQL dispatch scan (actions)",
            "status": "completed",
            "conclusion": "failure",
            "run_attempt": 1,
            "steps": [
                {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "failure"},
                {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
            ],
        },
    ]}

    result, post_log = _run_wake_step(
        tmp_path,
        statuses=statuses,
        producer_jobs=current_jobs,
        producer_artifacts={"artifacts": [
            {"name": "codeql-dispatch-actions-100-1", "expired": False}
        ]},
        predecessor_jobs=predecessor_jobs,
        predecessor_artifacts={"artifacts": [
            {"name": "codeql-dispatch-python-99-1", "expired": False}
        ]},
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "waiting for authenticated terminal receipts" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_reruns_whole_attempt_after_base_refresh(
    tmp_path: Path,
) -> None:
    """A refreshed base restarts successful capture and every matrix shard."""
    jobs = [
        {
            "id": 43, "run_id": 42, "run_attempt": 1, "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed", "conclusion": "success",
        },
        {
            "id": 44, "run_id": 42, "run_attempt": 1, "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "completed", "conclusion": "failure",
        },
    ]

    result, post_log = _run_wake_step(
        tmp_path,
        jobs=jobs,
        rerun_mode="all",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun"
    ]


def test_dispatch_settlement_recovers_forward_base_advance_after_scan(
    tmp_path: Path,
) -> None:
    """A base advance after dispatch validation restarts the exact required run."""
    result, post_log = _run_wake_step(
        tmp_path,
        pull={
            "state": "open",
            "head": {"sha": "b" * 40},
            "base": {"sha": "d" * 40, "ref": "main"},
        },
        base_compare={
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "base_commit": {"sha": "a" * 40},
            "merge_base_commit": {"sha": "a" * 40},
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun"
    ]


def test_dispatch_settlement_rejects_nonforward_late_base_change(
    tmp_path: Path,
) -> None:
    """A rewritten or divergent base cannot authorize a whole-run restart."""
    result, post_log = _run_wake_step(
        tmp_path,
        pull={
            "state": "open",
            "head": {"sha": "b" * 40},
            "base": {"sha": "d" * 40, "ref": "main"},
        },
        base_compare={
            "status": "diverged",
            "ahead_by": 1,
            "behind_by": 1,
            "base_commit": {"sha": "a" * 40},
            "merge_base_commit": {"sha": "e" * 40},
        },
    )

    assert result.returncode == 1
    assert "forward base advance" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_accepts_descendant_handler_source(
    tmp_path: Path,
) -> None:
    """Settlement authenticates a newer handler descended from producer source."""
    result, post_log = _run_wake_step(
        tmp_path,
        handler_source_sha="d" * 40,
        source_compare={
            "status": "ahead",
            "ahead_by": 1,
            "behind_by": 0,
            "base_commit": {"sha": "c" * 40},
            "merge_base_commit": {"sha": "c" * 40},
        },
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs"
    ]


def test_dispatch_wake_rejects_stale_head_and_closed_pr(tmp_path: Path) -> None:
    stale_result, stale_log = _run_wake_step(
        tmp_path / "stale",
        pull={
            "state": "open", "head": {"sha": "c" * 40},
            "base": {"sha": "a" * 40, "ref": "main"},
        },
    )
    closed_result, closed_log = _run_wake_step(
        tmp_path / "closed",
        pull={
            "state": "closed", "head": {"sha": "b" * 40},
            "base": {"sha": "a" * 40, "ref": "main"},
        },
    )

    assert stale_result.returncode == 1
    assert closed_result.returncode == 1
    assert not stale_log.exists()
    assert not closed_log.exists()


def test_dispatch_settlement_accepts_exact_scan_and_artifact_when_status_write_fails(
    tmp_path: Path,
) -> None:
    result, post_log = _run_wake_step(tmp_path, statuses=[])

    assert result.returncode == 0, result.stderr
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs"
    ]


def test_dispatch_settlement_reads_direct_evidence_on_later_pages(
    tmp_path: Path,
) -> None:
    """Settlement consumes complete paginated producer jobs and artifacts."""
    producer_jobs = [
        {
            "jobs": [
                {
                    "name": "validate-dispatch",
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        },
        {
            "jobs": [
                {
                    "name": f"CodeQL dispatch scan ({language})",
                    "status": "completed",
                    "conclusion": "failure",
                    "run_attempt": 1,
                    "steps": [
                        {
                            "name": "Enforce CodeQL Medium+ SARIF gate",
                            "conclusion": "success",
                        },
                        {
                            "name": "Preserve CodeQL SARIF evidence",
                            "conclusion": "success",
                        },
                    ],
                }
                for language in ("python", "actions")
            ]
        },
    ]
    producer_artifacts = [
        {"artifacts": []},
        {
            "artifacts": [
                {
                    "name": f"codeql-dispatch-{language}-100-1",
                    "expired": False,
                }
                for language in ("python", "actions")
            ]
        },
    ]

    result, post_log = _run_wake_step(
        tmp_path,
        statuses=[],
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/naruon/actions/runs/42/rerun-failed-jobs"
    ]


def test_dispatch_settlement_waits_when_receipt_and_direct_evidence_are_missing(
    tmp_path: Path,
) -> None:
    result, post_log = _run_wake_step(
        tmp_path,
        statuses=[],
        producer_jobs={"jobs": []},
    )

    assert result.returncode == 0, result.stderr
    assert "waiting for authenticated terminal receipts" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_accepts_exact_self_repository_workflow_token_receipts(
    tmp_path: Path,
) -> None:
    """The trusted handler accepts only its own exact-run GitHub-token fallback."""
    statuses = [
        {
            "context": f"codeql-dispatch/{language}/{'a' * 40}",
            "description": (
                f"cwl1;h={'b' * 40};w=codeql-scan-dispatch;r=42;"
                f"s={'c' * 40}"
            ),
            "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/100",
            "state": "success",
            "creator": {"login": "github-actions[bot]"},
        }
        for language in ("python", "actions")
    ]
    result, post_log = _run_wake_step(
        tmp_path,
        pull={
            "state": "open", "head": {"sha": "b" * 40},
            "base": {"sha": "a" * 40, "ref": "main"},
        },
        statuses=statuses,
        target_repository="ContextualWisdomLab/.github",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.read_text(encoding="utf-8").splitlines() == [
        "repos/ContextualWisdomLab/.github/actions/runs/42/rerun-failed-jobs"
    ]


def test_dispatch_settlement_rejects_failed_job_outside_exact_language_map(
    tmp_path: Path,
) -> None:
    jobs = [
        {
            "id": 43, "run_id": 42, "run_attempt": 1, "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed", "conclusion": "failure",
        },
        {
            "id": 44, "run_id": 42, "run_attempt": 1, "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "completed", "conclusion": "failure",
        },
        {
            "id": 45, "run_id": 42, "run_attempt": 1, "head_sha": "b" * 40,
            "name": "Unrelated failed gate",
            "status": "completed", "conclusion": "failure",
        },
    ]
    result, post_log = _run_wake_step(tmp_path, jobs=jobs)

    assert result.returncode == 1
    assert "failed jobs outside the exact language map" in result.stdout
    assert not post_log.exists()


def test_dispatch_settlement_rejects_ambiguous_or_nonfailed_job_identity(tmp_path: Path) -> None:
    wrong_jobs = [
        {
            "id": 43, "run_id": 999, "run_attempt": 1,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed", "conclusion": "failure",
        },
        {
            "id": 44, "run_id": 42, "run_attempt": 1,
            "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "completed", "conclusion": "failure",
        },
    ]
    wrong_job_result, wrong_job_log = _run_wake_step(
        tmp_path / "wrong-job",
        jobs=wrong_jobs,
    )
    successful_jobs = [dict(job) for job in wrong_jobs]
    successful_jobs[0].update(run_id=42, conclusion="success")
    successful_job_result, successful_job_log = _run_wake_step(
        tmp_path / "successful-job",
        jobs=successful_jobs,
    )

    assert wrong_job_result.returncode == 1
    assert successful_job_result.returncode == 1
    assert "missing or ambiguous exact run/job identity" in wrong_job_result.stdout
    assert not wrong_job_log.exists()
    assert not successful_job_log.exists()


def test_dispatch_settlement_accepts_403_only_after_exact_new_attempt_proof(
    tmp_path: Path,
) -> None:
    """A sibling 403 is settled only when both exact jobs have newer attempts."""
    newer_jobs = [
        {
            "id": 53, "run_id": 42, "run_attempt": 2, "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (python)",
            "status": "in_progress", "conclusion": None,
        },
        {
            "id": 54, "run_id": 42, "run_attempt": 2, "head_sha": "b" * 40,
            "name": "CodeQL compatibility analysis (actions)",
            "status": "queued", "conclusion": None,
        },
    ]
    result, post_log = _run_wake_step(
        tmp_path,
        post_failure=True,
        settled_jobs=newer_jobs,
    )

    assert result.returncode == 0, result.stderr
    assert post_log.exists()
    assert "exact newer attempts" in result.stdout


def test_dispatch_settlement_rejects_bare_403_without_exact_new_attempts(
    tmp_path: Path,
) -> None:
    result, post_log = _run_wake_step(tmp_path, post_failure=True)

    assert result.returncode == 1
    assert post_log.exists()
    assert "could not prove exact newer attempts" in result.stdout



def test_codeql_settlement_paginates_direct_evidence_collections() -> None:
    """Run-wide settlement must inspect every producer job and artifact page."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    job_lines = [
        line
        for line in workflow.splitlines()
        if "producer_jobs=" in line and "/jobs?filter=latest&per_page=100" in line
    ]
    artifact_lines = [
        line
        for line in workflow.splitlines()
        if "artifacts=" in line and "/artifacts?name=" in line
    ]

    assert len(job_lines) == 1
    assert len(artifact_lines) == 2
    assert "gh api --paginate --slurp" in job_lines[0]
    assert all("gh api --paginate --slurp" in line for line in artifact_lines)
    assert ".[]?.jobs[]?" in workflow
    assert ".[]?.artifacts[]?" in workflow


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
    assert (
        "SUPPLIED_REQUIRED_JOBS: ${{ toJSON(github.event.client_payload.required_jobs) }}"
        in workflow
    ), "SUPPLIED_REQUIRED_JOBS must be serialised with toJSON(); a bare array breaks template validation"
    assert (
        "SUPPLIED_REQUIRED_JOB_ID: ${{ github.event.client_payload.required_job_id || '' }}"
        in workflow
    ), "Queued pre-cutover payloads still supply required_job_id as a scalar"
    assert (
        "SUPPLIED_REQUIRED_LANGUAGE: ${{ github.event.client_payload.required_language || '' }}"
        in workflow
    ), "Queued pre-cutover payloads still supply required_language as a scalar"
