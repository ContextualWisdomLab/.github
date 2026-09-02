"""Regression for successful retirement of superseded OpenCode verdict polls."""

from __future__ import annotations

from pathlib import Path
import os
import subprocess


WORKFLOW_PATH = Path(".github/workflows/opencode-review.yml")


def _superseded_poll_guard() -> str:
    """Return the production in-loop moved-head guard from the OpenCode workflow."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    marker = '            if [ "${live_poll_head,,}" != "${HEAD_SHA,,}" ]; then\n'
    guard_body = workflow_text.split(marker, 1)[1].split("            fi\n", 1)[0]
    return marker + guard_body + "            fi\n"


def test_superseded_poll_retires_successfully() -> None:
    """A moved head must release stale required-review work without a false red status."""
    script = "\n".join(
        (
            "set -euo pipefail",
            'HEAD_SHA="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"',
            'live_poll_head="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"',
            _superseded_poll_guard(),
        )
    )
    result = subprocess.run(
        ["bash", "-c", script],
        check=False,
        capture_output=True,
        text=True,
        env=os.environ.copy(),
    )

    assert result.returncode == 0
    assert "retiring superseded Required OpenCode Review poll" in result.stdout
