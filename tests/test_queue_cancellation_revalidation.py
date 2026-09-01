"""Executable regressions for destructive queue-cancellation revalidation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "revalidate_queue_cancellation.sh"


def _run_pr_case(
    tmp_path: Path,
    *,
    snapshot_sha: str,
    pr_sha: str,
    ref_sha: str,
    run_sha: str,
    status: str = "queued",
    fail_lookup: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run the production helper against deterministic PR/run API doubles."""
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the queue-cancellation regression")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cancelled = tmp_path / "cancelled"
    pr_payload = json.dumps(
        {
            "state": "open",
            "head": {
                "repo": {"full_name": "ContextualWisdomLab/example"},
                "ref": "feature/race",
                "sha": pr_sha,
            },
        },
        separators=(",", ":"),
    )
    run_payload = json.dumps(
        {
            "event": "pull_request",
            "status": status,
            "head_sha": run_sha,
            "head_branch": "feature/race",
            "pull_requests": [{"number": 12}],
        },
        separators=(",", ":"),
    )
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
args="$*"
if [[ "$args" == *"/actions/runs/77/cancel"* ]]; then
  : > {cancelled!s}
  exit 0
fi
if [[ "$args" == *"/actions/runs/77"* ]]; then
  printf '%s\\n' '{run_payload}'
  exit 0
fi
if [[ "$args" == *"/pulls/12"* ]]; then
  {'exit 73' if fail_lookup == 'pr' else f"printf '%s\\n' '{pr_payload}'"}
  exit 0
fi
if [[ "$args" == *"/git/ref/heads/feature/race"* ]]; then
  {'exit 74' if fail_lookup == 'ref' else f"printf '%s\\n' '{ref_sha}'"}
  exit 0
fi
exit 79
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    snapshot = json.dumps(
        {"ContextualWisdomLab/example:feature/race": snapshot_sha},
        separators=(",", ":"),
    )
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "ContextualWisdomLab/example",
            "77",
            "main",
            "d" * 40,
            snapshot,
            "superseded",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result, cancelled.exists()


def _run_orphan_case(
    tmp_path: Path, *, event: str, status: str = "queued"
) -> tuple[subprocess.CompletedProcess[str], bool]:
    """Run an aged orphan candidate with no current PR/default authority."""
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the queue-cancellation regression")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cancelled = tmp_path / "cancelled"
    run_payload = json.dumps(
        {
            "event": event,
            "status": status,
            "head_sha": "a" * 40,
            "head_branch": "orphan/workflow",
            "pull_requests": [],
        },
        separators=(",", ":"),
    )
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
args="$*"
if [[ "$args" == *"/actions/runs/77/cancel"* ]]; then
  : > {cancelled!s}
  exit 0
fi
if [[ "$args" == *"/actions/runs/77"* ]]; then
  printf '%s\\n' '{run_payload}'
  exit 0
fi
exit 79
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "ContextualWisdomLab/example",
            "77",
            "main",
            "d" * 40,
            "{}",
            "aged-orphan",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    return result, cancelled.exists()


def test_post_classification_head_movement_fails_closed(tmp_path: Path) -> None:
    """A new exact head arriving after classification must never be cancelled."""
    result, cancelled = _run_pr_case(
        tmp_path,
        snapshot_sha="a" * 40,
        pr_sha="b" * 40,
        ref_sha="b" * 40,
        run_sha="b" * 40,
    )
    assert result.returncode == 0, result.stderr
    assert "moved after queue classification" in result.stdout
    assert not cancelled


@pytest.mark.parametrize("failed_lookup", ["pr", "ref"])
def test_final_lookup_failure_fails_closed(
    tmp_path: Path, failed_lookup: str
) -> None:
    """Unavailable final authoritative PR/ref state preserves the candidate."""
    current = "b" * 40
    result, cancelled = _run_pr_case(
        tmp_path,
        snapshot_sha=current,
        pr_sha=current,
        ref_sha=current,
        run_sha="a" * 40,
        fail_lookup=failed_lookup,
    )
    assert result.returncode == 0, result.stderr
    assert "could not be re-fetched" in result.stdout
    assert not cancelled


def test_current_head_is_preserved(tmp_path: Path) -> None:
    """Final live-ref validation preserves the sole current-head evidence."""
    current = "b" * 40
    result, cancelled = _run_pr_case(
        tmp_path,
        snapshot_sha=current,
        pr_sha=current,
        ref_sha=current,
        run_sha=current,
    )
    assert result.returncode == 0, result.stderr
    assert "authoritative current-head evidence" in result.stdout
    assert not cancelled


def test_proven_predecessor_is_cancelled(tmp_path: Path) -> None:
    """An unchanged final live ref may cancel a proven predecessor run."""
    current = "b" * 40
    result, cancelled = _run_pr_case(
        tmp_path,
        snapshot_sha=current,
        pr_sha=current,
        ref_sha=current,
        run_sha="a" * 40,
    )
    assert result.returncode == 0, result.stderr
    assert cancelled


@pytest.mark.parametrize(
    "event",
    ["workflow_dispatch", "workflow_run", "repository_dispatch", "issues"],
)
def test_aged_orphan_events_remain_cancellable(tmp_path: Path, event: str) -> None:
    """Final revalidation must not disable legacy aged-orphan queue cleanup."""
    result, cancelled = _run_orphan_case(tmp_path, event=event)
    assert result.returncode == 0, result.stderr
    assert cancelled


def test_aged_orphan_that_started_running_is_preserved(tmp_path: Path) -> None:
    """Aged-orphan mode applies only while the candidate is still queued."""
    result, cancelled = _run_orphan_case(
        tmp_path, event="workflow_dispatch", status="in_progress"
    )
    assert result.returncode == 0, result.stderr
    assert "no longer queued" in result.stdout
    assert not cancelled
