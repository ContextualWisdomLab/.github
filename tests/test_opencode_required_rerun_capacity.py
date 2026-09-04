"""Capacity contract for Required OpenCode dispatch and exact-run wakeup."""

import json
import os
from pathlib import Path
import subprocess

from tests.test_opencode_required_verdict_regression import HEAD, fail_closed_script


REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")


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


def test_stale_event_cannot_safely_use_native_cancel_in_progress() -> None:
    required = REQUIRED.read_text(encoding="utf-8")
    target = required.split("  opencode-review-target:\n", 1)[1].split(
        "\n  cancel-superseded-opencode-review-runs:", 1
    )[0]

    assert "cancel-in-progress: true" in target
    assert "first privileged action re-fetches the live PR metadata" in target
    assert (
        "separate cleanup job rejects an out-of-order stale synchronize event" in target
    )
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
