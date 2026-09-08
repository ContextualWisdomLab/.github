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
    assert 'receipt_context="codeql-dispatch/${LANGUAGE}/${PR_BASE_SHA}"' in workflow
    assert '--arg ctx "$receipt_context"' in workflow
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
    assert "github.run_attempt == 1" not in coordinator.split("\n    runs-on:", 1)[0]
    assert coordinator.count("repos/ContextualWisdomLab/.github/dispatches") == 1
    assert 'event_type:"codeql-scan"' in coordinator
    assert "required_jobs:$required_jobs" in coordinator
    assert "required_run_id:$required_run_id" in coordinator
    assert "required_job_id:$required_job_id" not in coordinator
    assert "required_language:$required_language" not in coordinator
    assert "actions/runs/${REQUIRED_RUN_ID}/jobs" in coordinator
    assert "CodeQL compatibility analysis (" in coordinator


def test_codeql_receipt_provenance_binds_the_exact_required_run() -> None:
    """A same-head/base receipt from another required run is not reusable."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    expected = (
        'expected_title="CodeQL Scan Dispatch ${TARGET_REPOSITORY}#${PR_NUMBER}'
        '@${PR_HEAD_SHA}/${PR_BASE_SHA}/${REQUIRED_RUN_ID}/${PRODUCER_SOURCE_SHA}"'
    )
    assert workflow.count(expected) == 4
    assert workflow.count("REQUIRED_RUN_ID: ${{ github.run_id }}") == 2
    assert workflow.count("PRODUCER_SOURCE_SHA: ${{ github.workflow_sha }}") == 2
    assert "producer_source_sha:$producer_source_sha" in workflow


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


def _codeql_status(
    state: str,
    *,
    creator: str = "opencode-agent[bot]",
    base_sha: str = "a" * 40,
    head_sha: str = "b" * 40,
    producer_source_sha: str = "c" * 40,
) -> dict[str, object]:
    """Return one provenance-bound CodeQL dispatch status fixture."""
    return {
        "context": f"codeql-dispatch/python/{base_sha}",
        "description": (
            f"cwl1;h={head_sha};w=codeql-scan-dispatch;r=42;"
            f"s={producer_source_sha}"
        ),
        "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/123",
        "state": state,
        "creator": {"login": creator},
    }


def _run_verdict_read(
    tmp_path: Path, statuses: list[dict], *, second_page: list[dict] | None = None,
    base: dict | None = None, env_overrides: dict[str, str] | None = None,
    expect_dispatch_failure: bool = False,
    target_repository: str = "ContextualWisdomLab/naruon",
    producer_run: dict[str, object] | None = None,
    producer_runs: list[dict[str, object]] | None = None,
    producer_jobs: dict[str, object] | list[dict[str, object]] | None = None,
    producer_artifacts: dict[str, object] | list[dict[str, object]] | None = None,
    predecessor_jobs: dict[str, object] | None = None,
    predecessor_artifacts: dict[str, object] | None = None,
    producer_state: str = "success",
) -> tuple[subprocess.CompletedProcess[str], subprocess.CompletedProcess[str]]:
    """Execute the real one-shot status read and verdict enforcement blocks."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    dispatch_script = _extract_run_block(workflow_text, DISPATCH_STEP_NAME)
    verdict_script = _extract_run_block(workflow_text, VERDICT_STEP_NAME)

    head_sha = "b" * 40
    live_pr = {
        "head": {"sha": head_sha}, "state": "open",
        "base": base if base is not None else {
            "repo": {"full_name": target_repository},
            "ref": "main", "sha": "a" * 40,
        },
    }
    producer_run = producer_run or {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "c" * 40,
        "status": "in_progress",
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            f"CodeQL Scan Dispatch {target_repository}#42@{head_sha}/"
            f"{'a' * 40}/42/{'c' * 40}"
        ),
    }
    producer_jobs = producer_jobs or {
        "jobs": [
            {
                "name": "validate-dispatch",
                "status": "completed",
                "conclusion": "success",
            },
            {
                "name": "CodeQL dispatch scan (python)",
                "status": "completed",
                "conclusion": producer_state,
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
            },
        ]
    }
    producer_artifacts = producer_artifacts or {
        "total_count": 1,
        "artifacts": [{
            "name": "codeql-dispatch-python-123-1",
            "expired": False,
        }],
    }
    incomplete_predecessor = dict(producer_run)
    incomplete_predecessor["id"] = 122
    producer_runs = producer_runs or [producer_run]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'printf "%s\\n" "$*" >>"$FAKE_CALL_LOG"\n'
        'test "$1" = api\n'
        'if [ "$#" = 2 ] && [ "$2" = "repos/${TARGET_REPOSITORY}/pulls/42" ]; then\n'
        "  printf '%s\\n' \"$FAKE_PULL_JSON\"\n"
        'elif [ "$#" = 2 ] && [[ "$2" == repos/ContextualWisdomLab/.github/compare/* ]]; then\n'
        "  printf '%s\\n' \"$FAKE_SOURCE_COMPARE_JSON\"\n"
        'elif [ "$#" = 4 ] && [ "$2" = --paginate ] && [ "$3" = --slurp ] &&\n'
        '  [ "$4" = "repos/${TARGET_REPOSITORY}/commits/${PR_HEAD_SHA}/statuses?per_page=100" ]; then\n'
        "  printf '%s\\n' \"$FAKE_STATUSES_JSON\"\n"
        'elif [ "$#" = 4 ] && [ "$2" = --paginate ] && [ "$3" = --slurp ] &&\n'
        '  [ "$4" = "repos/ContextualWisdomLab/.github/actions/workflows/codeql-scan-dispatch.yml/runs?event=repository_dispatch&per_page=100" ]; then\n'
        "  printf '%s\\n' \"$FAKE_PRODUCER_RUNS_JSON\"\n"
        'elif [ "$#" = 2 ] && [ "$2" = "repos/ContextualWisdomLab/.github/actions/runs/123" ]; then\n'
        "  printf '%s\\n' \"$FAKE_PRODUCER_RUN_JSON\"\n"
        'elif [ "$#" = 2 ] && [ "$2" = "repos/ContextualWisdomLab/.github/actions/runs/122" ]; then\n'
        "  printf '%s\\n' \"$FAKE_PREDECESSOR_RUN_JSON\"\n"
        'elif [ "$#" = 4 ] && [ "$2" = --paginate ] && [ "$3" = --slurp ] && [ "$4" = "repos/ContextualWisdomLab/.github/actions/runs/123/jobs?filter=latest&per_page=100" ]; then\n'
        "  printf '%s\\n' \"$FAKE_PRODUCER_JOBS_JSON\"\n"
        'elif [ "$#" = 4 ] && [ "$2" = --paginate ] && [ "$3" = --slurp ] && [ "$4" = "repos/ContextualWisdomLab/.github/actions/runs/123/artifacts?name=codeql-dispatch-python-123-1&per_page=100" ]; then\n'
        "  printf '%s\\n' \"$FAKE_PRODUCER_ARTIFACTS_JSON\"\n"
        'elif [ "$#" = 4 ] && [ "$2" = --paginate ] && [ "$3" = --slurp ] && [[ "$4" == repos/ContextualWisdomLab/.github/actions/runs/122/jobs* ]]; then\n'
        "  printf '%s\\n' \"$FAKE_PREDECESSOR_JOBS_JSON\"\n"
        'elif [ "$#" = 4 ] && [ "$2" = --paginate ] && [ "$3" = --slurp ] && [[ "$4" == repos/ContextualWisdomLab/.github/actions/runs/122/artifacts* ]]; then\n'
        "  printf '%s\\n' \"$FAKE_PREDECESSOR_ARTIFACTS_JSON\"\n"
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
        "FAKE_PRODUCER_RUN_JSON": json.dumps(producer_run),
        "FAKE_PREDECESSOR_RUN_JSON": json.dumps(incomplete_predecessor),
        "FAKE_PREDECESSOR_JOBS_JSON": json.dumps(
            [predecessor_jobs or {"jobs": []}]
        ),
        "FAKE_PREDECESSOR_ARTIFACTS_JSON": json.dumps(
            [predecessor_artifacts or {"artifacts": []}]
        ),
        "FAKE_PRODUCER_RUNS_JSON": json.dumps([{"workflow_runs": producer_runs}]),
        "FAKE_PRODUCER_JOBS_JSON": json.dumps(
            producer_jobs if isinstance(producer_jobs, list) else [producer_jobs]
        ),
        "FAKE_PRODUCER_ARTIFACTS_JSON": json.dumps(
            producer_artifacts if isinstance(producer_artifacts, list)
            else [producer_artifacts]
        ),
        "FAKE_SOURCE_COMPARE_JSON": json.dumps(
            {
                "status": "identical",
                "base_commit": {"sha": "c" * 40},
                "merge_base_commit": {"sha": "c" * 40},
            }
        ),
        "GH_TOKEN": "fake-token",
        "FAKE_CALL_LOG": str(tmp_path / "gh-calls"),
        "TARGET_REPOSITORY": target_repository,
        "GITHUB_REPOSITORY": target_repository,
        "PR_NUMBER": "42",
        "PR_HEAD_SHA": head_sha,
        "LANGUAGE": "python",
        "BUILD_MODE": "none",
        "PR_BASE_REF": "main",
        "PR_BASE_SHA": "a" * 40,
        "PR_HEAD_REF": "feature",
        "RUN_ATTEMPT": "2",
        "REQUIRED_RUN_ID": "42",
        "REQUIRED_JOB_ID": "43",
        "PRODUCER_SOURCE_SHA": "c" * 40,
        "GITHUB_OUTPUT": str(output),
        **(env_overrides or {}),
    }
    dispatch_result = subprocess.run(
        [bash], input=dispatch_script, text=True, capture_output=True, check=False,
        env=dispatch_env, timeout=60,
    )
    if expect_dispatch_failure:
        assert dispatch_result.returncode != 0, dispatch_result.stdout
    else:
        assert dispatch_result.returncode == 0, dispatch_result.stderr
    output_values = dict(
        line.split("=", 1) for line in (
            output.read_text(encoding="utf-8").splitlines() if output.exists() else []
        )
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


@pytest.mark.parametrize("field,value", [
    ("repo", {"full_name": "ContextualWisdomLab/other"}),
    ("repo", {}), ("ref", "other"), ("ref", ""), ("ref", 42),
    ("sha", "c" * 40), ("sha", ""), ("sha", "not-a-sha"),
])
def test_codeql_terminal_rejects_invalid_live_base_before_status_read(
    tmp_path: Path, field: str, value: object,
) -> None:
    """A genuine old success cannot excuse missing or changed event base inputs."""
    base = {"repo": {"full_name": "ContextualWisdomLab/naruon"},
            "ref": "main", "sha": "a" * 40}
    base[field] = value
    dispatch, verdict = _run_verdict_read(tmp_path, [
        {"context": "codeql-dispatch/python", "state": "success",
         "creator": {"login": "opencode-agent[bot]"}},
    ], base=base, expect_dispatch_failure=True)
    assert "base" in dispatch.stdout.lower()
    assert verdict.returncode == 1
    assert (tmp_path / "gh-calls").read_text().splitlines() == [
        "api repos/ContextualWisdomLab/naruon/pulls/42"
    ]


@pytest.mark.parametrize("field,value", [
    ("PR_BASE_SHA", ""), ("PR_BASE_SHA", "invalid"), ("PR_BASE_REF", ""),
])
def test_codeql_terminal_rejects_missing_or_malformed_event_base(
    tmp_path: Path, field: str, value: str,
) -> None:
    _dispatch, verdict = _run_verdict_read(tmp_path, [],
        env_overrides={field: value}, expect_dispatch_failure=True)
    assert verdict.returncode == 1
    assert (tmp_path / "gh-calls").read_text().splitlines() == [
        "api repos/ContextualWisdomLab/naruon/pulls/42"
    ]


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
            _codeql_status("success", creator="attacker"),
            _codeql_status("failure"),
        ],
        producer_state="failure",
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == 1, verdict_result.stderr
    assert "did not pass (state=failure)" in verdict_result.stdout


def test_codeql_pr_one_shot_read_accepts_the_opencode_agent_creator(tmp_path: Path) -> None:
    """A legitimate App receipt is accepted with complete producer evidence."""
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[
            _codeql_status("success")
        ],
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == 0, verdict_result.stderr
    assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout


def test_codeql_pr_accepts_self_repository_github_actions_receipt_only_from_exact_dispatch_run(
    tmp_path: Path,
) -> None:
    """The self-repository token fallback is trusted only through exact run provenance."""
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[_codeql_status("success", creator="github-actions[bot]")],
        target_repository="ContextualWisdomLab/.github",
    )

    assert dispatch_result.returncode == 0, dispatch_result.stderr + dispatch_result.stdout
    assert verdict_result.returncode == 0, verdict_result.stderr + verdict_result.stdout
    assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout


def test_codeql_pr_accepts_producer_source_distinct_from_target_base(
    tmp_path: Path,
) -> None:
    """Central workflow source and target PR base are independent identities."""
    producer_run = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "c" * 40,
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/.github#42@"
            + "b" * 40 + "/" + "a" * 40 + "/42/" + "c" * 40
        ),
    }
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[_codeql_status("success", creator="github-actions[bot]")],
        target_repository="ContextualWisdomLab/.github",
        producer_run=producer_run,
        env_overrides={"PRODUCER_SOURCE_SHA": "c" * 40},
    )

    assert dispatch_result.returncode == 0, dispatch_result.stderr + dispatch_result.stdout
    assert verdict_result.returncode == 0, verdict_result.stderr + verdict_result.stdout


def test_codeql_pr_accepts_direct_evidence_from_descendant_handler_source(
    tmp_path: Path,
) -> None:
    """A handler on newer protected main can serve an immutable older producer."""
    producer_run = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "d" * 40,
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/naruon#42@"
            + "b" * 40 + "/" + "a" * 40 + "/42/" + "c" * 40
        ),
    }
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        producer_run=producer_run,
        env_overrides={
            "FAKE_SOURCE_COMPARE_JSON": json.dumps(
                {
                    "status": "ahead",
                    "ahead_by": 1,
                    "behind_by": 0,
                    "base_commit": {"sha": "c" * 40},
                    "merge_base_commit": {"sha": "c" * 40},
                }
            )
        },
    )

    assert dispatch_result.returncode == 0, dispatch_result.stderr + dispatch_result.stdout
    assert verdict_result.returncode == 0, verdict_result.stderr + verdict_result.stdout
    assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout


def test_codeql_pr_reads_direct_evidence_on_later_job_and_artifact_pages(
    tmp_path: Path,
) -> None:
    """Direct evidence must not stop at the first jobs or artifacts page."""
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
                    "name": "CodeQL dispatch scan (python)",
                    "status": "completed",
                    "conclusion": "success",
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
            ]
        },
    ]
    producer_artifacts = [
        {"artifacts": []},
        {
            "artifacts": [
                {"name": "codeql-dispatch-python-123-1", "expired": False}
            ]
        },
    ]

    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
    )

    assert dispatch_result.returncode == 0, dispatch_result.stderr + dispatch_result.stdout
    assert verdict_result.returncode == 0, verdict_result.stderr + verdict_result.stdout
    assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout


def test_codeql_pr_selects_unique_complete_run_after_duplicate_title_predecessor(
    tmp_path: Path,
) -> None:
    """An incomplete same-title predecessor cannot hide one complete successor."""
    complete = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "c" * 40,
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/naruon#42@"
            + "b" * 40 + "/" + "a" * 40 + "/42/" + "c" * 40
        ),
    }
    incomplete = dict(complete)
    incomplete["id"] = 122

    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        producer_run=complete,
        producer_runs=[incomplete, complete],
    )

    assert dispatch_result.returncode == 0, dispatch_result.stderr + dispatch_result.stdout
    assert verdict_result.returncode == 0, verdict_result.stderr + verdict_result.stdout
    assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout


def test_codeql_pr_rejects_two_complete_duplicate_title_runs(
    tmp_path: Path,
) -> None:
    """Two evidence-complete same-title runs remain ambiguous and fail closed."""
    complete = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "c" * 40,
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/naruon#42@"
            + "b" * 40 + "/" + "a" * 40 + "/42/" + "c" * 40
        ),
    }
    second = dict(complete)
    second["id"] = 122
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

    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[],
        producer_run=complete,
        producer_runs=[second, complete],
        predecessor_jobs=predecessor_jobs,
        predecessor_artifacts={
            "artifacts": [
                {"name": "codeql-dispatch-python-122-1", "expired": False}
            ]
        },
        expect_dispatch_failure=True,
    )

    assert dispatch_result.returncode == 1
    assert verdict_result.returncode == 1


def test_codeql_pr_app_receipt_requires_exact_dispatch_evidence(
    tmp_path: Path,
) -> None:
    """App receipts with wrong, incomplete, or missing evidence fail closed."""
    valid_run: dict[str, object] = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "c" * 40,
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/naruon#42@"
            + "b" * 40 + "/" + "a" * 40 + "/42/" + "c" * 40
        ),
    }
    valid_jobs = {
        "jobs": [
            {
                "name": "CodeQL dispatch scan (python)",
                "status": "completed",
                "conclusion": "success",
                "run_attempt": 1,
            }
        ]
    }
    wrong_workflow = dict(valid_run)
    wrong_workflow["path"] = ".github/workflows/other.yml"
    in_progress = json.loads(json.dumps(valid_jobs))
    in_progress["jobs"][0]["status"] = "in_progress"

    for name, run, jobs, artifacts in (
        ("wrong-workflow", wrong_workflow, valid_jobs, None),
        ("in-progress", valid_run, in_progress, None),
        ("missing-artifact", valid_run, valid_jobs, {"artifacts": []}),
    ):
        dispatch_result, verdict_result = _run_verdict_read(
            tmp_path / name,
            statuses=[_codeql_status("success")],
            producer_run=run,
            producer_jobs=jobs,
            producer_artifacts=artifacts,
            expect_dispatch_failure=True,
        )
        assert dispatch_result.returncode == 1
        assert verdict_result.returncode == 1
        assert "without an authenticated terminal verdict" in dispatch_result.stdout


def test_codeql_coordinator_app_receipts_require_exact_dispatch_evidence(
    tmp_path: Path,
) -> None:
    """Coordinator redispatches when App statuses lack producer evidence."""
    statuses = [
        {
            "context": f"codeql-dispatch/{language}/{'a' * 40}",
            "description": (
                f"cwl1;h={'b' * 40};w=codeql-scan-dispatch;r=99;"
                f"s={'c' * 40}"
            ),
            "target_url": (
                "https://github.com/ContextualWisdomLab/.github/actions/runs/123"
            ),
            "state": "success",
            "creator": {"login": "opencode-agent[bot]"},
        }
        for language in ("python", "actions")
    ]
    result, post_log, _post_body = _run_coordinator(
        tmp_path,
        statuses=statuses,
        producer_jobs=[{"jobs": []}],
        producer_artifacts=[{"artifacts": []}],
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.exists()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event", "pull_request"),
        ("path", ".github/workflows/other.yml"),
        ("head_sha", "c" * 40),
        ("repository", {"full_name": "ContextualWisdomLab/other"}),
        ("actor", {"login": "attacker"}),
        ("triggering_actor", {"login": "attacker"}),
    ],
)
def test_codeql_pr_rejects_self_repository_fallback_without_exact_dispatch_provenance(
    tmp_path: Path, field: str, value: object,
) -> None:
    """A github-actions status alone cannot impersonate the protected dispatcher."""
    producer_run: dict[str, object] = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "c" * 40,
        "status": "in_progress",
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/.github#42@" + "b" * 40
            + "/" + "a" * 40 + "/42"
        ),
    }
    producer_run[field] = value
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[_codeql_status("success", creator="github-actions[bot]")],
        target_repository="ContextualWisdomLab/.github",
        producer_run=producer_run,
        expect_dispatch_failure=True,
    )

    assert dispatch_result.returncode == 1
    assert verdict_result.returncode == 1
    assert "without an authenticated terminal verdict" in dispatch_result.stdout


def test_codeql_pr_ignores_trusted_status_without_current_base_receipt(
    tmp_path: Path,
) -> None:
    """A trusted same-head verdict from an earlier base cannot satisfy this base."""
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[
            {
                "context": "codeql-dispatch/python",
                "state": "success",
                "creator": {"login": "opencode-agent[bot]"},
            },
            _codeql_status("failure"),
        ],
        producer_state="failure",
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == 1, verdict_result.stderr
    assert "did not pass (state=failure)" in verdict_result.stdout


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("context", f"codeql-dispatch/python/{'c' * 40}"),
        ("description", f"cwl1;h={'c' * 40};w=codeql-scan-dispatch"),
        ("description", f"cwl1;h={'b' * 40};w=other-workflow"),
        (
            "target_url",
            "https://github.com/ContextualWisdomLab/.github/actions/runs/not-a-run",
        ),
        ("target_url", "https://example.test/actions/runs/123"),
    ],
)
def test_codeql_pr_ignores_incomplete_or_mismatched_receipt(
    tmp_path: Path, field: str, value: str,
) -> None:
    """Every receipt identity field must match before a verdict is consumed."""
    invalid_status = _codeql_status("success")
    invalid_status[field] = value
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[invalid_status, _codeql_status("failure")],
        producer_state="failure",
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == 1, verdict_result.stderr
    assert "did not pass (state=failure)" in verdict_result.stdout


@pytest.mark.parametrize("state,exit_code", [("success", 0), ("failure", 1)])
def test_codeql_pr_reads_trusted_verdict_on_second_page(
    tmp_path: Path, state: str, exit_code: int
) -> None:
    """A full first page of forged successes cannot hide a later trusted verdict."""
    dispatch_result, verdict_result = _run_verdict_read(
        tmp_path,
        statuses=[
            _codeql_status("success", creator="attacker")
            for _ in range(100)
        ],
        second_page=[_codeql_status(state)],
        producer_state=state,
    )
    assert dispatch_result.returncode == 0, dispatch_result.stderr
    assert verdict_result.returncode == exit_code, verdict_result.stderr
    if state == "success":
        assert "Current-head CodeQL dispatch verdict for python: success." in verdict_result.stdout
    else:
        assert "did not pass (state=failure)" in verdict_result.stdout



def test_codeql_pr_paginates_every_direct_evidence_collection() -> None:
    """Shard and coordinator consumers must not stop at 100 jobs or artifacts."""
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

    assert len(job_lines) == 4
    assert len(artifact_lines) == 4
    assert all("gh api --paginate --slurp" in line for line in job_lines)
    assert all("gh api --paginate --slurp" in line for line in artifact_lines)
    assert workflow.count(".[]?.jobs[]?") >= 4
    assert workflow.count(".[]?.artifacts[]?") >= 4


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
        'if [ "${2:-}" = "--paginate" ] && [ "${3:-}" = "--slurp" ]; then\n'
        '  printf \'%s\\n\' "$FAKE_STATUSES_JSON"\n'
        'else case "$2" in\n'
        "  */pulls/*) printf '%s\\n' \"$FAKE_PULL_JSON\" ;;\n"
        "  *) exit 1 ;;\n"
        "esac; fi\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    output = tmp_path / "github-output"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps({
            "head": {"sha": head_sha}, "state": "open",
            "base": {
                "repo": {"full_name": "ContextualWisdomLab/naruon"},
                "ref": "main", "sha": "a" * 40,
            },
        }),
        "FAKE_STATUSES_JSON": json.dumps([[]]),
        "FAKE_POST_LOG": str(post_log),
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "PR_BASE_REF": "main",
        "PR_BASE_SHA": "a" * 40,
        "PR_HEAD_REF": "feature",
        "PR_HEAD_SHA": head_sha,
        "LANGUAGE": "python",
        "BUILD_MODE": "none",
        "RUN_ATTEMPT": "1",
        "REQUIRED_RUN_ID": "42",
        "PRODUCER_SOURCE_SHA": "c" * 40,
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
    producer_run: dict[str, object],
    producer_jobs: list[dict[str, object]],
    producer_artifacts: list[dict[str, object]],
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
        "  */statuses*) body=$FAKE_STATUSES_JSON ;;\n"
        "  */actions/workflows/codeql-scan-dispatch.yml/runs*) body=$FAKE_PRODUCER_RUNS_JSON ;;\n"
        "  */actions/runs/123/jobs*) body=$FAKE_PRODUCER_JOBS_JSON ;;\n"
        "  */actions/runs/123/artifacts*) body=$FAKE_PRODUCER_ARTIFACTS_JSON ;;\n"
        "  */actions/runs/123) body=$FAKE_PRODUCER_RUN_JSON ;;\n"
        "  */actions/runs/122/jobs*) body='[{\"jobs\":[]}]' ;;\n"
        "  */actions/runs/122/artifacts*) body='[{\"artifacts\":[]}]' ;;\n"
        "  */actions/runs/122) body=$FAKE_PREDECESSOR_RUN_JSON ;;\n"
        "  repos/ContextualWisdomLab/.github/compare/*) body=$FAKE_SOURCE_COMPARE_JSON ;;\n"
        "  */actions/runs/*/jobs*) body=$FAKE_JOBS_JSON ;;\n"
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
    producer_jobs: list[dict[str, object]] | None = None,
    producer_artifacts: list[dict[str, object]] | None = None,
    producer_runs: list[dict[str, object]] | None = None,
    handler_source_sha: str | None = None,
    source_compare: dict[str, object] | None = None,
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
        "base": {
            "repo": {"full_name": "ContextualWisdomLab/naruon"},
            "sha": "a" * 40, "ref": "main",
        },
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
    handler_source_sha = handler_source_sha or "c" * 40
    producer_run: dict[str, object] = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": handler_source_sha,
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/naruon#42@"
            + head_sha + "/" + "a" * 40 + "/99/" + "c" * 40
        ),
    }
    producer_jobs = producer_jobs or [{"jobs": []}]
    producer_artifacts = producer_artifacts or [{"artifacts": []}]
    incomplete_predecessor = dict(producer_run)
    incomplete_predecessor["id"] = 122
    producer_runs = producer_runs or [producer_run]
    fake_bin, post_log, post_body = _write_coordinator_fakes(
        tmp_path,
        pull=pull,
        jobs=jobs,
        statuses=statuses,
        producer_run=producer_run,
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
    )
    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), COORDINATOR_STEP_NAME
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "FAKE_JOBS_JSON": json.dumps(jobs),
        "FAKE_STATUSES_JSON": json.dumps([statuses]),
        "FAKE_PRODUCER_RUNS_JSON": json.dumps([{"workflow_runs": producer_runs}]),
        "FAKE_PRODUCER_RUN_JSON": json.dumps(producer_run),
        "FAKE_PREDECESSOR_RUN_JSON": json.dumps(incomplete_predecessor),
        "FAKE_PRODUCER_JOBS_JSON": json.dumps(producer_jobs),
        "FAKE_PRODUCER_ARTIFACTS_JSON": json.dumps(producer_artifacts),
        "FAKE_SOURCE_COMPARE_JSON": json.dumps(
            source_compare
            or {
                "status": "identical",
                "base_commit": {"sha": "c" * 40},
                "merge_base_commit": {"sha": "c" * 40},
            }
        ),
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
        "PRODUCER_SOURCE_SHA": "c" * 40,
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


def _coordinator_receipt_evidence(
    states: dict[str, str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return completed jobs and retained artifacts for coordinator receipts."""
    jobs = [
        {
            "name": f"CodeQL dispatch scan ({language})",
            "status": "completed",
            "conclusion": state,
            "run_attempt": 1,
        }
        for language, state in states.items()
    ]
    artifacts = [
        {
            "name": f"codeql-dispatch-{language}-123-1",
            "expired": False,
        }
        for language in states
    ]
    return [{"jobs": jobs}], [{"artifacts": artifacts}]


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


def test_codeql_coordinator_keeps_all_failed_jobs_when_one_language_is_pending(
    tmp_path: Path,
) -> None:
    """Run-wide settlement keeps every failed job while scanning only pending languages."""
    producer_jobs, producer_artifacts = _coordinator_receipt_evidence(
        {"python": "success"}
    )
    result, post_log, post_body = _run_coordinator(
        tmp_path,
        statuses=[
            {
                "context": f"codeql-dispatch/python/{'a' * 40}",
                "description": (
                    f"cwl1;h={'b' * 40};w=codeql-scan-dispatch;r=99;"
                    f"s={'c' * 40}"
                ),
                "target_url": (
                    "https://github.com/ContextualWisdomLab/.github/actions/runs/123"
                ),
                "state": "success",
                "creator": {"login": "opencode-agent[bot]"},
            }
        ],
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert post_log.exists()
    client = json.loads(post_body.read_text(encoding="utf-8"))["client_payload"]
    assert [entry["language"] for entry in client["matrix"]] == ["actions"]
    assert {
        entry["language"]: entry["job_id"] for entry in client["required_jobs"]
    } == {"python": 101, "actions": 102}


def test_codeql_coordinator_reads_direct_evidence_on_later_pages(
    tmp_path: Path,
) -> None:
    """Later-page job and artifact evidence prevents a redundant dispatch."""
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
                    "conclusion": "success",
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
                    "name": f"codeql-dispatch-{language}-123-1",
                    "expired": False,
                }
                for language in ("python", "actions")
            ]
        },
    ]

    result, post_log, _post_body = _run_coordinator(
        tmp_path,
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "already have authenticated terminal verdicts" in result.stdout
    assert not post_log.exists()


def test_codeql_coordinator_accepts_descendant_handler_source(
    tmp_path: Path,
) -> None:
    """Coordinator accepts direct evidence from compatible newer handler main."""
    producer_jobs = [
        {
            "jobs": [
                {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
                *[
                    {
                        "name": f"CodeQL dispatch scan ({language})",
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                        "steps": [
                            {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                            {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
                        ],
                    }
                    for language in ("python", "actions")
                ],
            ]
        }
    ]
    producer_artifacts = [
        {
            "artifacts": [
                {"name": f"codeql-dispatch-{language}-123-1", "expired": False}
                for language in ("python", "actions")
            ]
        }
    ]

    result, post_log, _post_body = _run_coordinator(
        tmp_path,
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
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
    assert "already have authenticated terminal verdicts" in result.stdout
    assert not post_log.exists()


def test_codeql_coordinator_selects_complete_duplicate_title_successor(
    tmp_path: Path,
) -> None:
    """Coordinator validates evidence before enforcing producer uniqueness."""
    complete_jobs = [
        {
            "jobs": [
                {"name": "validate-dispatch", "status": "completed", "conclusion": "success"},
                *[
                    {
                        "name": f"CodeQL dispatch scan ({language})",
                        "status": "completed",
                        "conclusion": "success",
                        "run_attempt": 1,
                        "steps": [
                            {"name": "Enforce CodeQL Medium+ SARIF gate", "conclusion": "success"},
                            {"name": "Preserve CodeQL SARIF evidence", "conclusion": "success"},
                        ],
                    }
                    for language in ("python", "actions")
                ],
            ]
        }
    ]
    complete_artifacts = [
        {
            "artifacts": [
                {"name": f"codeql-dispatch-{language}-123-1", "expired": False}
                for language in ("python", "actions")
            ]
        }
    ]
    complete = {
        "id": 123,
        "event": "repository_dispatch",
        "path": ".github/workflows/codeql-scan-dispatch.yml",
        "head_sha": "c" * 40,
        "repository": {"full_name": "ContextualWisdomLab/.github"},
        "actor": {"login": "opencode-agent[bot]"},
        "triggering_actor": {"login": "opencode-agent[bot]"},
        "head_branch": "main",
        "display_title": (
            "CodeQL Scan Dispatch ContextualWisdomLab/naruon#42@"
            + "b" * 40 + "/" + "a" * 40 + "/99/" + "c" * 40
        ),
    }
    incomplete = dict(complete)
    incomplete["id"] = 122

    result, post_log, _post_body = _run_coordinator(
        tmp_path,
        producer_jobs=complete_jobs,
        producer_artifacts=complete_artifacts,
        producer_runs=[incomplete, complete],
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "already have authenticated terminal verdicts" in result.stdout
    assert not post_log.exists()


def test_codeql_coordinator_excludes_successful_compatibility_jobs_from_settlement(
    tmp_path: Path,
) -> None:
    """Run-wide settlement carries only exact failed compatibility jobs."""
    producer_jobs, producer_artifacts = _coordinator_receipt_evidence(
        {"python": "success"}
    )
    result, _post_log, post_body = _run_coordinator(
        tmp_path,
        jobs={
            "total_count": 2,
            "jobs": [
                {
                    "id": 101,
                    "name": "CodeQL compatibility analysis (python)",
                    "status": "completed",
                    "conclusion": "success",
                },
                {
                    "id": 102,
                    "name": "CodeQL compatibility analysis (actions)",
                    "status": "completed",
                    "conclusion": "failure",
                },
            ],
        },
        statuses=[
            {
                "context": f"codeql-dispatch/python/{'a' * 40}",
                "description": (
                    f"cwl1;h={'b' * 40};w=codeql-scan-dispatch;r=99;"
                    f"s={'c' * 40}"
                ),
                "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/123",
                "state": "success",
                "creator": {"login": "opencode-agent[bot]"},
            }
        ],
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    client = json.loads(post_body.read_text(encoding="utf-8"))["client_payload"]
    assert client["required_jobs"] == [{"language": "actions", "job_id": 102}]


def test_codeql_coordinator_rejects_unrelated_failed_job_before_dispatch(
    tmp_path: Path,
) -> None:
    """A run-wide rerun cannot be authorized when another failed job exists."""
    result, post_log, _post_body = _run_coordinator(
        tmp_path,
        jobs={
            "total_count": 3,
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
                {
                    "id": 103,
                    "name": "Unrelated failed gate",
                    "status": "completed",
                    "conclusion": "failure",
                },
            ],
        },
    )

    assert result.returncode == 1
    assert "failed jobs outside the exact language map" in result.stdout
    assert not post_log.exists()


def test_codeql_coordinator_skips_dispatch_when_every_language_has_a_verdict(
    tmp_path: Path,
) -> None:
    """A rerun that already has terminal statuses must not enqueue another scan."""
    producer_jobs, producer_artifacts = _coordinator_receipt_evidence(
        {"python": "success", "actions": "failure"}
    )
    result, post_log, post_body = _run_coordinator(
        tmp_path,
        statuses=[
            {
                "context": f"codeql-dispatch/python/{'a' * 40}",
                "description": (
                    f"cwl1;h={'b' * 40};w=codeql-scan-dispatch;r=99;"
                    f"s={'c' * 40}"
                ),
                "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/123",
                "state": "success",
                "creator": {"login": "opencode-agent[bot]"},
            },
            {
                "context": f"codeql-dispatch/actions/{'a' * 40}",
                "description": (
                    f"cwl1;h={'b' * 40};w=codeql-scan-dispatch;r=99;"
                    f"s={'c' * 40}"
                ),
                "target_url": "https://github.com/ContextualWisdomLab/.github/actions/runs/123",
                "state": "failure",
                "creator": {"login": "opencode-agent[bot]"},
            },
        ],
        producer_jobs=producer_jobs,
        producer_artifacts=producer_artifacts,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert not post_log.exists()
    assert not post_body.exists() or post_body.read_text(encoding="utf-8") == ""
    assert "already have authenticated terminal verdicts" in result.stdout


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
