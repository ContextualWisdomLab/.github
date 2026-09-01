"""Regression for aged PR-run cancellation after late PR association."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "ci" / "revalidate_queue_cancellation.sh"


def test_aged_unassociated_pr_run_rechecks_open_pr_heads(tmp_path: Path) -> None:
    """A PR that appears after classification must preserve its current-head run."""
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
    open_prs = json.dumps(
        [
            {
                "state": "open",
                "head": {
                    "repo": {"full_name": "ContextualWisdomLab/example"},
                    "ref": "feature/late-pr",
                    "sha": current,
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

    assert result.returncode == 0, result.stderr
    assert "became associated with an open PR" in result.stdout
    assert not cancelled
