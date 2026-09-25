"""Stale OpenCode review dispatches end as a notice instead of a failure.

Under organization runner-queue saturation a repository_dispatch for an older
pull request head can start hours after the head moved or the pull request
closed. The newer dispatch is itself still queued, so the workflow-level
``cancel-in-progress`` group cannot retire the stale run first. The validate
step must then end the run with a ``::notice::`` and ``stale=true`` so the
coverage and review jobs skip, while every other metadata disagreement and any
failed lookup keeps failing closed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml"
VALIDATE_STEP_NAME = "Bind workflow inputs to live organization pull request metadata"
TARGET = "ContextualWisdomLab/naruon"


def _live_pull_request() -> dict:
    """A live PR payload matching the default supplied dispatch metadata."""
    return {
        "state": "open",
        "base": {
            "repo": {"full_name": TARGET, "visibility": "private"},
            "ref": "main",
            "sha": "a" * 40,
        },
        "head": {"repo": {"full_name": TARGET}, "ref": "feature", "sha": "b" * 40},
    }


def _run_validate_step(
    tmp_path: Path,
    pull_request: dict,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute the real validate-pr-metadata shell block against a fake `gh api`."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None, "bash and jq are required to run this test"

    script = _extract_run_block(WORKFLOW_PATH.read_text(encoding="utf-8"), VALIDATE_STEP_NAME)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        'endpoint="${!#}"\n'
        'printf \'%s\\n\' "$endpoint" >>"$FAKE_GH_LOG"\n'
        'case "$endpoint" in\n'
        '  repos/*/compare/*)\n'
        '    if [ -z "$FAKE_HEAD_COMPARE_JSON" ]; then echo \'HTTP 404\' >&2; exit 1; fi\n'
        '    printf \'%s\\n\' "$FAKE_HEAD_COMPARE_JSON" ;;\n'
        '  *) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        'esac\n',
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    output = tmp_path / "github-output"
    summary = tmp_path / "step-summary"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull_request),
        # Head-ancestry compare used by stale retirement; empty = lookup fails.
        "FAKE_HEAD_COMPARE_JSON": "",
        "FAKE_GH_LOG": str(tmp_path / "gh-calls.log"),
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(summary),
        "EVENT_NAME": "repository_dispatch",
        "DISPATCH_ACTOR": "opencode-agent[bot]",
        "DISPATCH_SENDER": "opencode-agent[bot]",
        "ALLOWED_DISPATCH_ACTOR": "opencode-agent[bot]",
        "ALLOWED_DISPATCH_TARGETS": TARGET,
        "TARGET_REPOSITORY": TARGET,
        "PR_NUMBER": "42",
        "SUPPLIED_BASE_REF": "main",
        "SUPPLIED_BASE_SHA": "a" * 40,
        "SUPPLIED_HEAD_REF": "feature",
        "SUPPLIED_HEAD_SHA": "b" * 40,
        **(env_overrides or {}),
    }
    result = subprocess.run([bash], input=script, text=True, capture_output=True, check=False, env=env)
    result.output_path = output  # type: ignore[attr-defined]
    result.summary_path = summary  # type: ignore[attr-defined]
    return result


def _outputs(result: subprocess.CompletedProcess[str]) -> str:
    path = result.output_path  # type: ignore[attr-defined]
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _assert_stale_skip(result: subprocess.CompletedProcess[str], reason: str) -> None:
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"::notice::Skipping stale OpenCode review dispatch for {TARGET}#42" in result.stdout
    assert reason in result.stdout
    assert "::error::" not in result.stdout
    outputs = _outputs(result)
    assert "stale=true\n" in outputs
    assert "stale=false" not in outputs
    assert "head_sha=" not in outputs
    assert "base_sha=" not in outputs
    summary = result.summary_path.read_text(encoding="utf-8")  # type: ignore[attr-defined]
    assert f"Skipped stale OpenCode review dispatch for {TARGET}#42" in summary


def test_current_head_dispatch_is_not_stale(tmp_path):
    result = _run_validate_step(tmp_path, _live_pull_request())

    assert result.returncode == 0, result.stdout + result.stderr
    outputs = _outputs(result)
    assert "stale=false\n" in outputs
    assert f"head_sha={'b' * 40}\n" in outputs
    assert "::notice::Skipping stale" not in result.stdout


AHEAD_COMPARE_JSON = json.dumps({"status": "ahead", "ahead_by": 2, "behind_by": 0})


def test_moved_head_dispatch_is_skipped_with_notice(tmp_path):
    pull_request = _live_pull_request()
    pull_request["head"]["sha"] = "c" * 40

    result = _run_validate_step(tmp_path, pull_request, {"FAKE_HEAD_COMPARE_JSON": AHEAD_COMPARE_JSON})

    _assert_stale_skip(result, "pull request head moved ahead of the dispatched head")
    assert f"dispatched head={'b' * 40}, live head={'c' * 40}" in result.stdout
    # dispatched...live order: "ahead" means the live head descends from the dispatched head.
    calls = (tmp_path / "gh-calls.log").read_text(encoding="utf-8").splitlines()
    assert f"repos/{TARGET}/compare/{'b' * 40}...{'c' * 40}" in calls


def test_head_mismatch_without_proven_ancestry_stays_fail_closed(tmp_path):
    """Only a live head that provably descends from the dispatched head retires the run.

    API lag right after a push (live=previous head, compare "behind"), force-push
    ("diverged"), and any failed or contradictory compare answer keep the original
    fail-closed head_sha mismatch, so a fresh head is never silently skipped.
    """
    cases = {
        "api_lag_behind": json.dumps({"status": "behind", "ahead_by": 0, "behind_by": 1}),
        "force_push_diverged": json.dumps({"status": "diverged", "ahead_by": 1, "behind_by": 3}),
        "ahead_but_behind_by": json.dumps({"status": "ahead", "ahead_by": 1, "behind_by": 1}),
        "ahead_without_counts": json.dumps({"status": "ahead"}),
        "not_json": "<html>busy</html>",
        "lookup_failed": "",
    }
    for name, compare_json in cases.items():
        pull_request = _live_pull_request()
        pull_request["head"]["sha"] = "c" * 40
        result = _run_validate_step(tmp_path / name, pull_request, {"FAKE_HEAD_COMPARE_JSON": compare_json})
        assert result.returncode == 1, (name, result.stdout, result.stderr)
        assert "does not match the live pull request: head_sha" in result.stdout, name
        assert "Not retiring OpenCode review dispatch" in result.stdout, name
        assert "::notice::Skipping stale" not in result.stdout, name
        assert "stale=true" not in _outputs(result), name


def test_non_dispatch_event_is_never_retired(tmp_path):
    """The EVENT_NAME guard mirrors the script's dispatch-only authorization and binding.

    For any other event the step never authorizes a dispatcher and ignores the
    supplied head, binding to the live head instead, so there is no dispatched head
    that could be stale. A moved supplied head must not retire the run, and a
    closed pull request keeps failing closed.
    """
    moved_head = _live_pull_request()
    moved_head["head"]["sha"] = "c" * 40
    override = {"EVENT_NAME": "workflow_dispatch", "FAKE_HEAD_COMPARE_JSON": AHEAD_COMPARE_JSON}

    result = _run_validate_step(tmp_path / "moved_head", moved_head, override)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "::notice::Skipping stale" not in result.stdout
    outputs = _outputs(result)
    assert "stale=false\n" in outputs and "stale=true" not in outputs
    assert f"head_sha={'c' * 40}\n" in outputs

    closed = _live_pull_request()
    closed["state"] = "closed"
    result = _run_validate_step(tmp_path / "closed", closed, override)
    assert result.returncode == 1
    assert "rejected closed, missing, or malformed live metadata" in result.stdout
    assert "::notice::Skipping stale" not in result.stdout
    assert "stale=true" not in _outputs(result)


def test_closed_pull_request_dispatch_is_skipped_with_notice(tmp_path):
    pull_request = _live_pull_request()
    pull_request["state"] = "closed"

    result = _run_validate_step(tmp_path, pull_request)

    _assert_stale_skip(result, "pull request is closed")


def test_other_metadata_disagreements_stay_fail_closed(tmp_path):
    moved_base = _live_pull_request()
    moved_base["base"]["sha"] = "e" * 40
    renamed_head_ref = _live_pull_request()
    renamed_head_ref["head"]["ref"] = "other"
    malformed_head = _live_pull_request()
    malformed_head["head"]["sha"] = "not-a-sha"
    missing_state = _live_pull_request()
    del missing_state["state"]

    cases = {
        "moved_base": (moved_base, "does not match the live pull request: base_sha"),
        "renamed_head_ref": (renamed_head_ref, "does not match the live pull request: head_ref"),
        "malformed_head": (malformed_head, "rejected closed, missing, or malformed live metadata"),
        "missing_state": (missing_state, "rejected closed, missing, or malformed live metadata"),
    }
    for name, (pull_request, message) in cases.items():
        result = _run_validate_step(tmp_path / name, pull_request)
        assert result.returncode == 1, name
        assert message in result.stdout, name
        assert "::notice::Skipping stale" not in result.stdout, name
        assert "stale=true" not in _outputs(result), name


def test_unauthorized_dispatch_is_rejected_before_stale_detection(tmp_path):
    pull_request = _live_pull_request()
    pull_request["head"]["sha"] = "c" * 40

    result = _run_validate_step(
        tmp_path,
        pull_request,
        {"DISPATCH_SENDER": "someone-else", "FAKE_HEAD_COMPARE_JSON": AHEAD_COMPARE_JSON},
    )

    assert result.returncode == 1
    assert "repository_dispatch authorization rejected" in result.stdout
    assert "stale=true" not in _outputs(result)


def test_failed_lookup_is_not_treated_as_stale(tmp_path):
    failing_bin = tmp_path / "failing-bin"
    failing_bin.mkdir()
    failing_gh = failing_bin / "gh"
    failing_gh.write_text("#!/usr/bin/env bash\necho 'HTTP 502' >&2\nexit 1\n", encoding="utf-8")
    failing_gh.chmod(0o755)

    result = _run_validate_step(
        tmp_path / "run",
        _live_pull_request(),
        {"PATH": f"{failing_bin}:{os.environ['PATH']}"},
    )

    assert result.returncode != 0
    assert "::notice::Skipping stale" not in result.stdout
    assert "stale=true" not in _outputs(result)


def test_stale_output_gates_every_later_step_and_job():
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    metadata_job = workflow.split("  validate-pr-metadata:\n", 1)[1].split("\n  coverage-evidence:\n", 1)[0]
    coverage_header = workflow.split("\n  coverage-evidence:\n", 1)[1].split("    runs-on:", 1)[0]
    review_header = workflow.split("\n  opencode-review-target:\n", 1)[1].split("    concurrency:", 1)[0]

    assert "stale: ${{ steps.validate.outputs.stale }}" in metadata_job
    later_steps = metadata_job.split(f"      - name: {VALIDATE_STEP_NAME}\n", 1)[1].split("\n      - name: ")[1:]
    assert later_steps, "validate must be followed by the coverage materialization steps"
    for step in later_steps:
        assert "steps.validate.outputs.stale != 'true'" in step, step.splitlines()[0]
    assert "needs.validate-pr-metadata.outputs.stale != 'true'" in coverage_header
    assert "needs.validate-pr-metadata.outputs.stale != 'true'" in review_header
