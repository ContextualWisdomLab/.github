"""Failure contracts for bounded sandbox service capture startup."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci import bounded_subprocess as bounded
from scripts.ci import sandboxed_web_e2e


class _RunningProcess:
    """Minimal process double active until explicitly killed and waited."""

    pid = 200
    stdout = object()

    def __init__(self) -> None:
        self.returncode: int | None = None
        self.waited = False

    def poll(self) -> int | None:
        """Return the current process state."""

        return self.returncode

    def wait(self, timeout=None) -> int:
        """Record reaping and return the terminal status."""

        del timeout
        self.waited = True
        self.returncode = -9
        return self.returncode


def test_capture_startup_failure_kills_and_reaps_the_service(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A failed drainer cannot leave an unobserved long-running child behind."""

    process = _RunningProcess()
    monkeypatch.setattr(bounded, "require_supported_platform", lambda: None)
    monkeypatch.setattr(
        sandboxed_web_e2e.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    monkeypatch.setattr(
        bounded,
        "start_bounded_capture",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("capture startup failed")
        ),
    )
    killed: list[object] = []
    monkeypatch.setattr(
        bounded,
        "kill_process_group",
        lambda candidate: killed.append(candidate),
    )

    with pytest.raises(RuntimeError, match="capture startup failed"):
        sandboxed_web_e2e.start_service(
            "backend",
            "tool",
            tmp_path,
            {},
            tmp_path,
            4096,
        )

    assert killed == [process]
    assert process.waited is True
