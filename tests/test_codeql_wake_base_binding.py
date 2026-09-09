"""Fail-closed contract for CodeQL wake identity across pull-request base changes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-scan-dispatch.yml"


def _run_wake(
    tmp_path: Path,
    *,
    live_base_sha: str,
    run_base_sha: str,
    live_base_ref: str = "main",
    run_base_ref: str = "main",
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Execute the production wake block against base-aware GitHub API fixtures."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    assert bash is not None and jq is not None

    expected_base_sha = "a" * 40
    head_sha = "b" * 40
    pull = {
        "state": "open",
        "number": 42,
        "base": {"sha": live_base_sha, "ref": live_base_ref},
        "head": {"sha": head_sha},
    }
    run = {
        "id": 42,
        "event": "pull_request",
        "path": ".github/workflows/codeql-pr.yml",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "failure",
        "pull_requests": [
            {
                "number": 42,
                "head": {"sha": head_sha},
                "base": {"sha": run_base_sha, "ref": run_base_ref},
            }
        ],
    }
    jobs = [
        {
            "id": 43,
            "run_id": 42,
            "head_sha": head_sha,
            "name": "CodeQL compatibility analysis (python)",
            "status": "completed",
            "conclusion": "failure",
        }
    ]

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
        "  exit 0\n"
        "fi\n"
        'case "$2" in\n'
        '  */pulls/*) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        '  */actions/runs/*) printf \'%s\\n\' "$FAKE_RUN_JSON" ;;\n'
        '  */actions/jobs/*) printf \'%s\\n\' "$FAKE_JOB_JSON" ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"), "Wake exact CodeQL required run"
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "FAKE_RUN_JSON": json.dumps(run),
        "FAKE_JOB_JSON": json.dumps(jobs[0]),
        "FAKE_POST_LOG": str(post_log),
        "GH_TOKEN": "fake-token",
        "WAKE_TOKEN_SOURCE": "PR_REVIEW_MERGE_TOKEN",
        "TARGET_REPOSITORY": "ContextualWisdomLab/naruon",
        "PR_NUMBER": "42",
        "BASE_REF": "main",
        "BASE_SHA": expected_base_sha,
        "HEAD_SHA": head_sha,
        "REQUIRED_RUN_ID": "42",
        "REQUIRED_JOBS": json.dumps([{"language": "python", "job_id": 43}]),
    }
    result = subprocess.run(
        [bash], input=script, text=True, capture_output=True, check=False, env=env
    )
    return result, post_log


def test_wake_rejects_same_head_after_live_base_change(tmp_path: Path) -> None:
    """Retargeting only the PR base invalidates an earlier validated wake identity."""
    result, post_log = _run_wake(
        tmp_path,
        live_base_sha="c" * 40,
        run_base_sha="a" * 40,
    )

    assert result.returncode == 1
    assert not post_log.exists()


def test_wake_rejects_required_run_created_for_other_base(tmp_path: Path) -> None:
    """An exact-head run from another base cannot authorize the current PR wake."""
    result, post_log = _run_wake(
        tmp_path,
        live_base_sha="a" * 40,
        run_base_sha="c" * 40,
    )

    assert result.returncode == 1
    assert not post_log.exists()


def test_wake_rejects_same_base_sha_under_another_base_ref(tmp_path: Path) -> None:
    """A same-SHA retarget to another branch invalidates the wake identity."""
    result, post_log = _run_wake(
        tmp_path,
        live_base_sha="a" * 40,
        run_base_sha="a" * 40,
        live_base_ref="release",
        run_base_ref="release",
    )

    assert result.returncode == 1
    assert not post_log.exists()
