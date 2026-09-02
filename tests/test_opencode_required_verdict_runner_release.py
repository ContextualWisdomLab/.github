"""Regression coverage for releasing the required OpenCode runner while review continues."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


WORKFLOW = Path(".github/workflows/opencode-review.yml")
DISPATCH_WORKFLOW = Path(".github/workflows/opencode-review-dispatch.yml")
HEAD_SHA = "a" * 40


def _fail_closed_script() -> str:
    """Extract the real required-verdict admission step body."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    step = workflow.split(
        "      - name: Fail closed without a current-head OpenCode verdict\n", 1
    )[1]
    return textwrap.dedent(step.split("        run: |\n", 1)[1])


def test_missing_verdict_uses_exact_run_wake_instead_of_runner_polling() -> None:
    """A missing verdict must fail once and rely on the authenticated exact-run wake."""
    required = _fail_closed_script()
    dispatched = DISPATCH_WORKFLOW.read_text(encoding="utf-8")

    assert "while :; do" not in required
    assert "poll_interval_seconds" not in required
    assert "poll_deadline_epoch" not in required
    assert "sleep " not in required
    assert "rerun-failed-jobs" in dispatched
    assert "github.event.client_payload.required_run_id != ''" in dispatched
    assert 'gh api "repos/${GH_REPOSITORY}/actions/runs/${REQUIRED_RUN_ID}"' in dispatched
    assert 'select(.event == "pull_request_target")' in dispatched
    assert 'select(.path == ".github/workflows/opencode-review.yml")' in dispatched
    assert "select(.head_sha == $head)" in dispatched


def test_missing_verdict_fails_after_one_live_read_and_one_review_read(tmp_path: Path) -> None:
    """Execute the production step and prove it never sleeps or loops without a verdict."""
    bash = shutil.which("bash")
    jq = shutil.which("jq")
    if bash is None or jq is None:
        pytest.skip("bash and jq are required to execute the production verdict step")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    call_log = tmp_path / "gh-calls"
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\\n' "$*" >>"$FAKE_CALL_LOG"
if [[ "$*" == "api repos/ContextualWisdomLab/example/pulls/42" ]]; then
  printf '%s\\n' "$FAKE_LIVE_PR"
  exit 0
fi
if [[ "$*" == "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100" ]]; then
  printf '%s\\n' '[]'
  exit 0
fi
printf 'unexpected gh call: %s\\n' "$*" >&2
exit 97
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)

    fake_timeout = fake_bin / "timeout"
    fake_timeout.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nshift\nexec \"$@\"\n",
        encoding="utf-8",
    )
    fake_timeout.chmod(0o755)

    fake_sleep = fake_bin / "sleep"
    fake_sleep.write_text(
        "#!/usr/bin/env bash\nprintf 'unexpected sleep\\n' >&2\nexit 91\n",
        encoding="utf-8",
    )
    fake_sleep.chmod(0o755)

    result = subprocess.run(
        [bash, "-c", _fail_closed_script()],
        env={
            **os.environ,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_CALL_LOG": str(call_log),
            "FAKE_LIVE_PR": json.dumps(
                {"head": {"sha": HEAD_SHA}, "draft": False, "state": "open"}
            ),
            "GH_TOKEN": "test-token",
            "TARGET_REPOSITORY": "ContextualWisdomLab/example",
            "PR_NUMBER": "42",
            "HEAD_SHA": HEAD_SHA,
            "PR_ACTION": "synchronize",
            "PR_DRAFT": "false",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1, result.stderr
    assert "unexpected sleep" not in result.stderr
    assert "No APPROVED or CHANGES_REQUESTED from opencode-agent" in result.stdout
    assert call_log.read_text(encoding="utf-8").splitlines() == [
        "api repos/ContextualWisdomLab/example/pulls/42",
        "api --paginate repos/ContextualWisdomLab/example/pulls/42/reviews?per_page=100",
    ]
