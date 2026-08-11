"""Checks for the stdlib timeout fallback used by local review tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ci" / "portable_timeout.py"


def test_portable_timeout_returns_child_status() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "1s",
            "5s",
            "--",
            sys.executable,
            "-c",
            "print('ok')",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout == "ok\n"


def test_portable_timeout_returns_124_after_killing_child() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "0.1s",
            "0.1s",
            "--",
            sys.executable,
            "-c",
            "import time; time.sleep(2)",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert result.returncode == 124
