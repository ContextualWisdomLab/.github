"""Capacity contract for Required OpenCode dispatch and exact-run wakeup."""

import json
import os
from pathlib import Path
import subprocess

from tests.test_opencode_required_verdict_regression import HEAD, fail_closed_script


REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")


def test_live_head_admission_reuses_the_trusted_bootstrap_runner() -> None:
    """Keep admission and policy order without a second runner or lost contexts."""
    required = REQUIRED.read_text(encoding="utf-8")
    bootstrap = required.split("  required-workflow-bootstrap:\n", 1)[1].split(
        "\n  coverage-source-tree:\n", 1
    )[0]
    assert "\n  admit-current-head:\n" not in required
    assert required.count("runs-on:") == 5
    assert "admitted: ${{ steps.live_head.outputs.admitted }}" in bootstrap
    assert "id: live_head\n        timeout-minutes: 5\n" in bootstrap
    assert bootstrap.index("Enforce Cloudflare Pingora edge policy") < bootstrap.index(
        "Admit only the exact live OpenCode head"
    )
    assert "GITHUB_ENV" not in bootstrap
    assert "GITHUB_PATH" not in bootstrap
    assert "actions/checkout" not in bootstrap
    assert "${{ secrets." not in bootstrap
    assert required.count("needs: [required-workflow-bootstrap]") == 3
    assert required.count(
        "if: needs.required-workflow-bootstrap.outputs.admitted == 'true'"
    ) == 3
    assert "    name: coverage-source-tree\n" in required
    assert "    name: coverage-evidence\n" in required


def test_required_job_releases_runner_until_exact_run_wakeup() -> None:
    required = REQUIRED.read_text(encoding="utf-8")
    target = required.split("  opencode-review-target:\n", 1)[1].split(
        "\n  cancel-superseded-opencode-review-runs:", 1
    )[0]

    assert "repos/ContextualWisdomLab/.github/dispatches" in target
    assert "required_run_id" in target
    assert "while :; do" not in target
    assert "poll_interval_seconds" not in target
    assert "sleep " not in target
    assert "will rerun this failed job" in target


def test_dispatch_wakes_only_the_exact_failed_current_head_run() -> None:
    dispatch = DISPATCH.read_text(encoding="utf-8")
    wake = dispatch.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1].split(
        "\n\n      - name:", 1
    )[0]

    assert "github.event.client_payload.required_run_id != ''" in wake
    assert "select(.id == $run_id)" in wake
    assert 'select(.event == "pull_request_target")' in wake
    assert 'select(.path == ".github/workflows/opencode-review.yml")' in wake
    assert "select(.head_sha == $head)" in wake
    assert "rerun-failed-jobs" in wake


def test_native_cancellation_runs_before_runner_admission() -> None:
    required = REQUIRED.read_text(encoding="utf-8")
    concurrency = required.split("\nconcurrency:\n", 1)[1].split(
        "\npermissions:\n", 1
    )[0]

    assert "required-opencode-review-${{" in concurrency
    assert "github.event.pull_request.number || github.run_id" in concurrency
    assert "cancel-in-progress: true" in concurrency
    assert "live_head_matches()" in required


def test_missing_verdict_fails_after_one_review_read(tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$CALLS"
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  printf '%s' "$LIVE_PR"
elif [[ "$*" == *"/pulls/7/reviews?per_page=100"* ]]; then
  printf '[]'
else
  exit 19
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", fail_closed_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls),
            "GH_TOKEN": "token",
            "TARGET_REPOSITORY": "owner/repo",
            "PR_NUMBER": "7",
            "HEAD_SHA": HEAD,
            "PR_ACTION": "synchronize",
            "PR_DRAFT": "false",
            "LIVE_PR": json.dumps(
                {"draft": False, "head": {"sha": HEAD}, "state": "open"}
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "will rerun this failed job" in result.stdout
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "api repos/owner/repo/pulls/7",
        "api --paginate repos/owner/repo/pulls/7/reviews?per_page=100",
    ]
