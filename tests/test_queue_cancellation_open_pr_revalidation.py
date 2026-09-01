"""Regressions for aged PR-run cancellation after late PR association."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "revalidate_queue_cancellation.sh"


def _run_late_association_case(
    tmp_path: Path, *, payload_sha: str, live_ref_sha: str, fail_ref: bool = False
) -> tuple[subprocess.CompletedProcess[str], bool]:
    if shutil.which("jq") is None:
        pytest.skip("jq is required for the queue-cancellation regression")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cancelled = tmp_path / "cancelled"
    current = "b" * 40
    run_payload = json.dumps(
        {
            "event": "pull_request",
            "status": "queued",
            "head_sha": current,
            "head_branch": "feature/late-pr",
            "head_repository": {"full_name": "ContextualWisdomLab/example"},
            "pull_requests": [],
        },
        separators=(",", ":"),
    )
    # Deliberately include a payload SHA that may lag the authoritative branch
    # ref. The helper must use this response only to discover repo/ref identity.
    open_prs = json.dumps(
        [
            {
                "state": "open",
                "head": {
                    "repo": {"full_name": "ContextualWisdomLab/example"},
                    "ref": "feature/late-pr",
                    "sha": payload_sha,
                },
            }
        ],
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
if [[ "$args" == *"/pulls?state=open&per_page=100"* ]]; then
  printf '%s\\n' '{open_prs}'
  exit 0
fi
if [[ "$args" == *"/git/ref/heads/feature/late-pr"* ]]; then
  {'exit 74' if fail_ref else f"printf '%s\\n' '{live_ref_sha}'"}
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


def test_aged_unassociated_pr_run_resolves_authoritative_live_ref(tmp_path: Path) -> None:
    """A stale PR payload cannot authorize cancellation of the live current head."""
    current = "b" * 40
    stale_payload = "a" * 40
    result, cancelled = _run_late_association_case(
        tmp_path,
        payload_sha=stale_payload,
        live_ref_sha=current,
    )

    assert result.returncode == 0, result.stderr
    assert "authoritative current head" in result.stdout
    assert not cancelled


def test_aged_unassociated_pr_run_fails_closed_when_live_ref_is_unreadable(
    tmp_path: Path,
) -> None:
    """A matching late PR with unreadable ref must preserve the queued run."""
    result, cancelled = _run_late_association_case(
        tmp_path,
        payload_sha="a" * 40,
        live_ref_sha="b" * 40,
        fail_ref=True,
    )

    assert result.returncode == 0, result.stderr
    assert "could not be re-fetched" in result.stdout
    assert not cancelled
