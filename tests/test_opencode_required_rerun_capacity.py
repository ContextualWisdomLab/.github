"""Capacity contract for Required OpenCode dispatch and exact-run wakeup."""

from tests.test_required_workflow_queue_contract import (
    workflow_level_cancels_in_progress,
)
import json
import os
from pathlib import Path
import subprocess
import textwrap

from tests.test_opencode_required_verdict_regression import HEAD, fail_closed_script


REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")


def wake_failed_required_runs_script() -> str:
    """Extract the exact production wake step shell."""
    dispatch = DISPATCH.read_text(encoding="utf-8")
    step = dispatch.split(
        "      - name: Wake every failed exact-head Required OpenCode workflow\n", 1
    )[1].split("\n\n      - name:", 1)[0]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def required_run(run_id: int, *, pr_number: int = 7) -> dict[str, object]:
    """Build one exact-head required-workflow list record."""
    return {
        "id": run_id,
        "event": "pull_request_target",
        "path": ".github/workflows/opencode-review.yml",
        "head_sha": "c" * 40,
        "status": "completed",
        "conclusion": "failure",
        "pull_requests": [{"number": pr_number, "head": {"sha": HEAD}}],
    }


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


def test_dispatch_wakes_every_exact_failed_current_head_run() -> None:
    dispatch = DISPATCH.read_text(encoding="utf-8")
    wake = dispatch.split(
        "      - name: Wake every failed exact-head Required OpenCode workflow\n", 1
    )[1].split("\n\n      - name:", 1)[0]

    assert "github.event.client_payload.required_run_id != ''" not in wake
    assert '.event == "pull_request_target"' in wake
    assert '.path == ".github/workflows/opencode-review.yml"' in wake
    assert "(.head.sha | ascii_downcase) == ($head | ascii_downcase)" in wake
    assert ".number == $pr" in wake
    assert "unique_by(.id)" in wake
    assert "rerun-failed-jobs" in wake
    assert "actions/workflows/opencode-review.yml/runs" not in wake
    assert "actions/runs?event=pull_request_target&created=" in wake
    assert "range_total" in wake
    assert "expected_total" in wake
    assert "live_authority_matches" in wake


def test_dispatch_wake_binds_shared_head_runs_to_exact_pull_request(
    tmp_path: Path,
) -> None:
    """Wake all failures for this PR and none for another PR sharing its head."""
    calls = tmp_path / "calls"
    fake_gh = tmp_path / "gh"
    inventory = {
        "total_count": 3,
        "workflow_runs": [
            required_run(41),
            required_run(42, pr_number=8),
            required_run(43),
        ]
    }
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$CALLS"
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  printf '%s' "$LIVE_PR"
elif [[ "$*" == *"repos/owner/repo/actions/runs?"* ]]; then
  printf '%s' "$RUN_INVENTORY"
elif [[ "$*" == *"rerun-failed-jobs"* ]]; then
  exit 0
else
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", wake_failed_required_runs_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls),
            "GH_TOKEN": "token",
            "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
            "GH_REPOSITORY": "owner/repo",
            "PR_NUMBER": "7",
            "PR_HEAD_SHA": HEAD,
            "LIVE_PR": json.dumps(
                {
                    "state": "open",
                    "draft": False,
                    "created_at": "2026-09-30T00:00:00Z",
                    "head": {"sha": HEAD},
                }
            ),
            "RUN_INVENTORY": json.dumps(inventory),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    reruns = [line for line in calls.read_text().splitlines() if "rerun-failed-jobs" in line]
    assert reruns == [
        "api -X POST repos/owner/repo/actions/runs/41/rerun-failed-jobs",
        "api -X POST repos/owner/repo/actions/runs/43/rerun-failed-jobs",
    ]
    assert calls.read_text().count("api repos/owner/repo/pulls/7") == 3


def test_dispatch_wake_stops_when_live_authority_moves_between_mutations(
    tmp_path: Path,
) -> None:
    """Revalidate the live open head immediately before every rerun POST."""
    calls = tmp_path / "calls"
    authority_reads = tmp_path / "authority-reads"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$CALLS"
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  count=0
  [[ ! -f "$AUTHORITY_READS" ]] || count="$(cat "$AUTHORITY_READS")"
  count=$((count + 1))
  printf '%s' "$count" >"$AUTHORITY_READS"
  if [[ "$count" -lt 3 ]]; then head="$PR_HEAD_SHA"; else head="$(printf 'd%.0s' {1..40})"; fi
  jq -cn --arg head "$head" '{state:"open",draft:false,created_at:"2026-09-30T00:00:00Z",head:{sha:$head}}'
elif [[ "$*" == *"repos/owner/repo/actions/runs?"* ]]; then
  printf '%s' "$RUN_INVENTORY"
elif [[ "$*" == *"rerun-failed-jobs"* ]]; then
  exit 0
else
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", wake_failed_required_runs_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls),
            "AUTHORITY_READS": str(authority_reads),
            "GH_TOKEN": "token",
            "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
            "GH_REPOSITORY": "owner/repo",
            "PR_NUMBER": "7",
            "PR_HEAD_SHA": HEAD,
            "RUN_INVENTORY": json.dumps(
                {
                    "total_count": 2,
                    "workflow_runs": [required_run(41), required_run(43)],
                }
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "authority changed before Required OpenCode rerun 43" in result.stdout
    reruns = [line for line in calls.read_text().splitlines() if "rerun-failed-jobs" in line]
    assert reruns == ["api -X POST repos/owner/repo/actions/runs/41/rerun-failed-jobs"]


def test_dispatch_wake_reports_partial_rerun_api_failure(tmp_path: Path) -> None:
    """A later rerun failure must fail the publisher after recording prior work."""
    calls = tmp_path / "calls"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$CALLS"
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  jq -cn --arg head "$PR_HEAD_SHA" '{state:"open",draft:false,created_at:"2026-09-30T00:00:00Z",head:{sha:$head}}'
elif [[ "$*" == *"repos/owner/repo/actions/runs?"* ]]; then
  printf '%s' "$RUN_INVENTORY"
elif [[ "$*" == *"actions/runs/41/rerun-failed-jobs"* ]]; then
  exit 0
elif [[ "$*" == *"actions/runs/43/rerun-failed-jobs"* ]]; then
  exit 22
else
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", wake_failed_required_runs_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls),
            "GH_TOKEN": "token",
            "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
            "GH_REPOSITORY": "owner/repo",
            "PR_NUMBER": "7",
            "PR_HEAD_SHA": HEAD,
            "RUN_INVENTORY": json.dumps(
                {
                    "total_count": 2,
                    "workflow_runs": [required_run(41), required_run(43)],
                }
            ),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 22
    reruns = [line for line in calls.read_text().splitlines() if "rerun-failed-jobs" in line]
    assert reruns == [
        "api -X POST repos/owner/repo/actions/runs/41/rerun-failed-jobs",
        "api -X POST repos/owner/repo/actions/runs/43/rerun-failed-jobs",
    ]


def test_dispatch_wake_partitions_inventory_above_github_search_cap(
    tmp_path: Path,
) -> None:
    """Bisect GitHub's overflow sentinel before collecting bounded pages."""
    calls = tmp_path / "calls"
    probe_count = tmp_path / "probe-count"
    page_count = tmp_path / "page-count"
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"$CALLS"
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  jq -cn --arg head "$PR_HEAD_SHA" '{state:"open",draft:false,created_at:"2026-09-30T00:00:00Z",head:{sha:$head}}'
elif [[ "$*" == *"actions/runs?"* && "$*" == *"per_page=1" ]]; then
  count=0
  [[ ! -f "$PROBE_COUNT" ]] || count="$(cat "$PROBE_COUNT")"
  count=$((count + 1))
  printf '%s' "$count" >"$PROBE_COUNT"
  case "$count" in
    1) printf '%s' '{"total_count":"2,500+","workflow_runs":[]}' ;;
    2) printf '%s' '{"total_count":1,"workflow_runs":[]}' ;;
    3) printf '%s' '{"total_count":0,"workflow_runs":[]}' ;;
    *) exit 96 ;;
  esac
elif [[ "$*" == *"api --paginate"* && "$*" == *"per_page=100"* ]]; then
  count=0
  [[ ! -f "$PAGE_COUNT" ]] || count="$(cat "$PAGE_COUNT")"
  count=$((count + 1))
  printf '%s' "$count" >"$PAGE_COUNT"
  if [[ "$count" -eq 1 ]]; then printf '%s' "$ONE_RUN"; else printf '%s' '{"workflow_runs":[]}'; fi
elif [[ "$*" == *"actions/runs/41/rerun-failed-jobs"* ]]; then
  exit 0
else
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", wake_failed_required_runs_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "CALLS": str(calls),
            "PROBE_COUNT": str(probe_count),
            "PAGE_COUNT": str(page_count),
            "GH_TOKEN": "token",
            "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
            "GH_REPOSITORY": "owner/repo",
            "PR_NUMBER": "7",
            "PR_HEAD_SHA": HEAD,
            "ONE_RUN": json.dumps({"workflow_runs": [required_run(41)]}),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert probe_count.read_text() == "3"
    assert page_count.read_text() == "2"
    assert "actions/runs/41/rerun-failed-jobs" in calls.read_text()


def test_dispatch_wake_fails_when_overflow_shares_one_second(tmp_path: Path) -> None:
    """A non-partitionable overflow sentinel fails before run selection."""
    fake_gh = tmp_path / "gh"
    fake_date = tmp_path / "date"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  jq -cn --arg head "$PR_HEAD_SHA" '{state:"open",draft:false,created_at:"2026-09-30T00:00:00Z",head:{sha:$head}}'
elif [[ "$*" == *"actions/runs?"* && "$*" == *"per_page=1" ]]; then
  printf '%s' '{"total_count":"2,500+","workflow_runs":[]}'
else
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_date.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "-u +%Y-%m-%dT%H:%M:%SZ" ]]; then
  printf '%s\n' '2026-09-30T00:00:00Z'
elif [[ "$*" == *"+%s"* ]]; then
  printf '%s\n' '1'
else
  exit 98
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_date.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", wake_failed_required_runs_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "token",
            "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
            "GH_REPOSITORY": "owner/repo",
            "PR_NUMBER": "7",
            "PR_HEAD_SHA": HEAD,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "More than 1,000 pull_request_target runs share one second" in result.stderr


def test_dispatch_wake_rejects_paginated_inventory_truncation(tmp_path: Path) -> None:
    """Compare API total_count with collected rows before selecting mutations."""
    fake_gh = tmp_path / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$*" == "api repos/owner/repo/pulls/7" ]]; then
  jq -cn --arg head "$PR_HEAD_SHA" '{state:"open",draft:false,created_at:"2026-09-30T00:00:00Z",head:{sha:$head}}'
elif [[ "$*" == *"actions/runs?"* && "$*" == *"per_page=1" ]]; then
  printf '%s' '{"total_count":2,"workflow_runs":[]}'
elif [[ "$*" == *"api --paginate"* && "$*" == *"per_page=100"* ]]; then
  printf '%s' "$ONE_RUN"
else
  exit 97
fi
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    result = subprocess.run(
        ["bash", "-c", wake_failed_required_runs_script()],
        env={
            **os.environ,
            "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "token",
            "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
            "GH_REPOSITORY": "owner/repo",
            "PR_NUMBER": "7",
            "PR_HEAD_SHA": HEAD,
            "ONE_RUN": json.dumps({"workflow_runs": [required_run(41)]}),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "inventory was truncated: expected=2 collected=1" in result.stderr


def test_native_cancellation_runs_before_runner_admission() -> None:
    required = REQUIRED.read_text(encoding="utf-8")
    concurrency = required.split("\nconcurrency:\n", 1)[1].split(
        "\npermissions:\n", 1
    )[0]

    assert "required-opencode-review-${{" in concurrency
    assert "github.event.pull_request.number || github.run_id" in concurrency
    assert workflow_level_cancels_in_progress(required)
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
