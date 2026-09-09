"""Fail-closed tests for CodeQL terminal verdict identity across PR base changes."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from tests.test_opencode_workflow_shell_syntax import _extract_run_block

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github/workflows/codeql-pr.yml"


def _run_shard_verdict_reader_with_stale_status(
    tmp_path: Path,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    """Run the production shard reader with only a head-scoped old-base status."""
    bash = shutil.which("bash")
    assert bash is not None, "bash is required to run this test"

    head_sha = "b" * 40
    live_base_sha = "c" * 40
    pull = {
        "state": "open",
        "number": 42,
        "base": {"sha": live_base_sha},
        "head": {"sha": head_sha},
    }
    # GitHub commit statuses have no PR-base or required-run identity. This
    # terminal status represents evidence left on the same head by an earlier
    # base/run and therefore must not authorize the current shard by itself.
    statuses = [
        {
            "context": "codeql-dispatch/python",
            "state": "success",
            "creator": {"login": "opencode-agent[bot]"},
        }
    ]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(parents=True)
    output = tmp_path / "github-output"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'test "$1" = api\n'
        "shift\n"
        'case "$*" in\n'
        '  *"pulls/42"*) printf \'%s\\n\' "$FAKE_PULL_JSON" ;;\n'
        '  *"statuses"*) printf \'%s\\n\' "$FAKE_STATUSES_JSON" ;;\n'
        '  *"codeql-scan-dispatch.yml/runs"*) printf \'%s\\n\' \'[{"workflow_runs":[]}]\' ;;\n'
        "  *) exit 1 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    script = _extract_run_block(
        WORKFLOW_PATH.read_text(encoding="utf-8"),
        "Read current-head CodeQL dispatch verdict",
    )
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "FAKE_PULL_JSON": json.dumps(pull),
        "FAKE_STATUSES_JSON": json.dumps(statuses),
        "GH_TOKEN": "fake-token",
        "TARGET_REPOSITORY": "ContextualWisdomLab/example",
        "PR_NUMBER": "42",
        "PR_HEAD_SHA": head_sha,
        "LANGUAGE": "python",
        "RUN_ATTEMPT": "1",
        "REQUIRED_RUN_ID": "99",
        "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        [bash],
        input=script,
        text=True,
        capture_output=True,
        check=False,
        env=env,
        timeout=60,
    )
    return result, output


def test_shard_rejects_terminal_status_without_exact_base_run_binding(
    tmp_path: Path,
) -> None:
    """A same-head status from another base/run is not terminal evidence."""
    result, output = _run_shard_verdict_reader_with_stale_status(tmp_path)

    assert result.returncode == 0, result.stderr + result.stdout
    assert output.read_text(encoding="utf-8").splitlines() == ["verdict=pending"]
    assert "Found authenticated current-head CodeQL verdict" not in result.stdout


def test_coordinator_does_not_suppress_dispatch_from_head_only_statuses() -> None:
    """Pending-language admission must be derived from exact dispatch-run identity."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    coordinator = workflow.split("  dispatch-current-head:\n", 1)[1]

    assert 'commits/${PR_HEAD_SHA}/statuses' not in coordinator
