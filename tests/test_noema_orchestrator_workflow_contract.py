"""Noema review now uses the vendored orchestrator sidecar, not NVIDIA NIM."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import textwrap
from pathlib import Path

from tests.test_required_workflow_queue_contract import workflow_step, workflow_text


def test_noema_close_cleanup_selects_only_the_closed_pr_from_one_snapshot(
    tmp_path: Path,
) -> None:
    """Execute cleanup against shared-SHA runs and cancel only the closed PR."""
    script = textwrap.dedent(
        workflow_step(
            workflow_text("noema-review.yml"),
            "Cancel queued and running Noema reviews for the closed pull request",
        ).split("        run: |\n", 1)[1].split("\n  noema-review:", 1)[0]
    )
    runs = {
        "workflow_runs": [
            {
                "id": 101,
                "name": "Required Noema Review",
                "display_title": "Required Noema Review ContextualWisdomLab/demo#7@" + "a" * 40,
                "head_sha": "a" * 40,
                "status": "requested",
            },
            {
                "id": 102,
                "name": "Required Noema Review",
                "display_title": "Required Noema Review ContextualWisdomLab/demo#8@" + "a" * 40,
                "head_sha": "a" * 40,
                "status": "queued",
            },
            {
                "id": 103,
                "name": "Required Noema Review",
                "display_title": "Required Noema Review ContextualWisdomLab/demo#7@" + "a" * 40,
                "head_sha": "a" * 40,
                "status": "completed",
            },
        ]
    }
    runs_file = tmp_path / "runs.json"
    runs_file.write_text(json.dumps(runs), encoding="utf-8")
    calls_file = tmp_path / "calls.txt"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == *"--paginate"* ]]; then
  cat "$FAKE_RUNS_FILE"
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
            "CLOSED_PR_NUMBER": "7",
            "CLOSED_PR_HEAD_SHA": "a" * 40,
            "CURRENT_RUN_ID": "999",
            "FAKE_RUNS_FILE": str(runs_file),
            "FAKE_CALLS_FILE": str(calls_file),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    calls = calls_file.read_text(encoding="utf-8")
    assert "/actions/runs/101/cancel" in calls
    assert "/actions/runs/102/cancel" not in calls
    assert "/actions/runs/103/cancel" not in calls


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
    assert "python3 -m scripts.ci.noema_review_gate" in workflow
    assert "python3 scripts/ci/noema_review_gate.py" not in workflow
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


def test_workflow_run_expected_head_uses_pull_request_head_not_base_commit() -> None:
    """EXPECTED_HEAD for a workflow_run completion must resolve the PR head, not the base.

    Devin Review finding on PR #1507: ``github.event.workflow_run.head_sha``
    is the base/trusted commit the completing ``pull_request_target``
    workflow (Required OpenCode Review / Strix Security Scan) checked out —
    not the PR head — so every workflow_run-triggered follow-up review used
    to fail the stale-trigger gate. The fix reuses this same workflow's own
    established pattern for ``PR_NUMBER`` (``pull_requests[0].number``) and
    reads the actual PR head from ``pull_requests[0].head.sha`` instead.
    """
    workflow = workflow_text("noema-review.yml")
    assert (
        "EXPECTED_HEAD: ${{ github.event.client_payload.pr_head_sha || "
        "github.event.pull_request.head.sha || "
        "github.event.workflow_run.pull_requests[0].head.sha || '' }}"
    ) in workflow
    assert "EXPECTED_HEAD: ${{ github.event.client_payload.pr_head_sha || github.event.pull_request.head.sha || github.event.workflow_run.head_sha || '' }}" not in workflow

    base_sha = "b" * 40
    pr_head_sha = "a" * 40
    assert base_sha != pr_head_sha
    workflow_run_event = {
        "workflow_run": {
            # The top-level head_sha on a workflow_run object completing a
            # pull_request_target run is the base/trusted commit that run
            # checked out (its own github.sha) -- not the PR's head.
            "head_sha": base_sha,
            "pull_requests": [
                {"number": 42, "head": {"sha": pr_head_sha}, "base": {"sha": base_sha}}
            ],
        }
    }
    assert _expected_head_from_workflow_run_event(workflow_run_event) == pr_head_sha
    assert _expected_head_from_workflow_run_event(workflow_run_event) != base_sha


def test_workflow_run_expected_head_fails_closed_when_pull_requests_is_empty() -> None:
    """A fork-originated workflow_run (empty pull_requests[]) yields no expected head.

    ``pull_requests`` is documented to come back empty for cross-fork PRs;
    EXPECTED_HEAD must fall through to '' rather than fabricate a head, and
    PR_NUMBER (already sourced from the same array) falls through the same
    way, so the job's existing "Skip events without pull request context"
    step still short-circuits the run before any stale-head comparison.
    """
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
    fake_gh.write_text(
        f"#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s' '{live_head}'\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}",
        "TARGET_REPOSITORY": "ContextualWisdomLab/example",
        "PR_NUMBER": "7",
        "EXPECTED_HEAD": expected_head,
        "GH_TOKEN": "synthetic-token",
    }
    return subprocess.run(  # noqa: S603, S607
        [bash_executable, "-c", step_script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_stale_trigger_step_compares_expected_head_case_insensitively(
    tmp_path: Path,
) -> None:
    """An uppercase EXPECTED_HEAD must not be rejected against GitHub's lowercase live SHA.

    Devin Review finding on PR #1507: this bash-side stale-trigger guard
    accepts uppercase hex (its own regex allows it, matching
    ``--expected-head``'s Python-side validation) but used to compare
    case-sensitively against the live PR head GitHub's API always reports in
    lowercase, rejecting every valid uppercase-cased dispatch as stale.
    """
    sha = "a" * 40
    result = _run_stale_trigger_step(tmp_path, expected_head=sha.upper(), live_head=sha)
    assert result.returncode == 0, result.stderr
    assert "is stale" not in result.stdout


def test_stale_trigger_step_still_rejects_a_genuinely_different_head(
    tmp_path: Path,
) -> None:
    """A truly stale trigger (different commit, any case) is still rejected."""
    result = _run_stale_trigger_step(
        tmp_path, expected_head="A" * 40, live_head="b" * 40
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
            "Run Noema LLM review and submit verdict",
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
