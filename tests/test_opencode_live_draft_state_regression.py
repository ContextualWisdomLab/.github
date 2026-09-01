"""Regression coverage for live draft/head validation in required OpenCode review."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from tests.test_opencode_required_verdict_regression import (
    HEAD,
    fail_closed_script,
    request_review_script,
)


def _write_live_state_gh(
    bin_dir: Path,
    *,
    live_draft: bool,
    live_head: str = HEAD,
    later_exit: int = 19,
) -> None:
    """Serve the live PR lookup, then fail if the step reaches later GitHub I/O."""
    payload = json.dumps({"draft": live_draft, "head": {"sha": live_head}})
    fake_gh = bin_dir / "gh"
    fake_gh.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/pulls/1437\" ]]; then\n"
        f"  printf '%s' {json.dumps(payload)}\n"
        "  exit 0\n"
        "fi\n"
        f"exit {later_exit}\n",
        encoding="utf-8",
    )
    fake_gh.chmod(fake_gh.stat().st_mode | 0o111)


def _run_step(
    tmp_path: Path,
    script: str,
    *,
    live_draft: bool,
    live_head: str = HEAD,
    action: str = "converted_to_draft",
) -> subprocess.CompletedProcess[str]:
    """Execute one production step with stale draft event metadata."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production step body")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_live_state_gh(bin_dir, live_draft=live_draft, live_head=live_head)
    return subprocess.run(
        [bash, "-c", script],
        env={
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "GH_TOKEN": "fake-token",
            "OIDC_AUDIENCE": "opencode-github-action",
            "OPENCODE_API_BASE_URL": "https://api.opencode.ai",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "1437",
            "HEAD_SHA": HEAD,
            "PR_ACTION": action,
            "PR_DRAFT": "true",
            "BASE_BRANCH": "main",
            "WORKFLOW_SHA": "c" * 40,
        },
        text=True,
        capture_output=True,
        check=False,
    )


def test_stale_draft_request_event_does_not_exempt_live_ready_pr(
    tmp_path: Path,
) -> None:
    """A stale draft request snapshot continues into the ready-PR review path."""
    result = _run_step(tmp_path, request_review_script(), live_draft=False)

    assert result.returncode == 19
    assert "Event draft snapshot is stale" in result.stdout


def test_stale_draft_verdict_event_does_not_exempt_live_ready_pr(
    tmp_path: Path,
) -> None:
    """A stale draft verdict snapshot cannot publish a success for a ready PR."""
    result = _run_step(tmp_path, fail_closed_script(), live_draft=False)

    assert result.returncode == 19
    assert "Event draft snapshot is stale" in result.stdout


@pytest.mark.parametrize("script", (request_review_script(), fail_closed_script()))
def test_draft_exemption_fails_closed_when_live_head_moved(
    tmp_path: Path,
    script: str,
) -> None:
    """The event cannot exempt a different live head even when it is still draft."""
    result = _run_step(tmp_path, script, live_draft=True, live_head="b" * 40)

    assert result.returncode == 1
    assert "head moved while validating draft" in result.stdout
