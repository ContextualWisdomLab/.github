"""Regression coverage for one-shot Required OpenCode verdict admission."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REQUIRED = Path(".github/workflows/opencode-review.yml")
DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")
HEAD = "a" * 40


def _required_script() -> str:
    """Return the production exact-head verdict-admission shell body."""
    text = REQUIRED.read_text(encoding="utf-8")
    step = text.split("      - name: Fail closed without a current-head OpenCode verdict\n", 1)[1]
    return textwrap.dedent(step.split("        run: |\n", 1)[1].split("\n  cancel-superseded-opencode-review-runs:\n", 1)[0])


def _wake() -> str:
    """Return the production formal-receipt exact-run wake step."""
    text = DISPATCH.read_text(encoding="utf-8")
    return text.split("      - name: Wake exact-head required OpenCode workflow\n", 1)[1].split("\n      - name: Publish repository_dispatch OpenCode status\n", 1)[0]


def test_missing_verdict_releases_runner_without_local_wait_allocation() -> None:
    """Admission performs complete state reads once and never polls or sleeps."""
    step = _required_script()
    assert step.count('gh api "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}"') == 1
    assert step.count('gh api --paginate "repos/${TARGET_REPOSITORY}/pulls/${PR_NUMBER}/reviews') == 1
    for token in ("while :; do", "poll_interval_seconds", "poll_deadline_epoch", "max_poll_transport_failures", "sleep ", "timeout "):
        assert token not in step


def test_receipt_wake_binds_exact_pr_head_and_run_without_polling() -> None:
    """Authenticated receipt wake is one exact-state transition."""
    step = _wake()
    for token in ("for attempt", "while :; do", "seq 1", "sleep ", "timeout ", "/12", "--paginate"):
        assert token not in step
    assert "pull_requests // []" in step
    assert "rerun-failed-jobs" in step
    assert "advanced concurrently" in step


def test_missing_verdict_fails_after_one_live_and_one_reviews_read(tmp_path: Path) -> None:
    """No formal verdict causes exactly two GitHub reads and an immediate failure."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required")
    calls = tmp_path / "calls"
    gh = tmp_path / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$*\" >>\"$CALLS\"\n"
        "if [[ \"$*\" == \"api repos/ContextualWisdomLab/example/pulls/42\" ]]; then printf '%s\\n' \"$LIVE_PR\"; exit 0; fi\n"
        "if [[ \"$*\" == \"api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100\" ]]; then printf '[]\\n'; exit 0; fi\n"
        "exit 97\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    result = subprocess.run(
        [bash, "-c", _required_script()],
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}", "CALLS": str(calls), "LIVE_PR": json.dumps({"head": {"sha": HEAD}, "draft": False, "state": "open"}), "GH_TOKEN": "token", "TARGET_REPOSITORY": "ContextualWisdomLab/example", "PR_NUMBER": "42", "HEAD_SHA": HEAD, "PR_ACTION": "synchronize", "PR_DRAFT": "false"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1, result.stderr
    assert len(calls.read_text(encoding="utf-8").splitlines()) == 2
