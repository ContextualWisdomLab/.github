"""Regression contracts for bounded command capture-startup cleanup."""

from __future__ import annotations

import io
from pathlib import Path
from typing import cast

import pytest

from scripts.ci import bounded_subprocess as bounded


class _TrackedStream(io.BytesIO):
    """Binary pipe double whose closed state remains observable."""


class _Process:
    """Minimal running process double with two parent-side output pipes."""

    pid = 4242

    def __init__(self) -> None:
        """Create open stdout and stderr streams and cleanup counters."""

        self.stdout = _TrackedStream(b"stdout")
        self.stderr = _TrackedStream(b"stderr")
        self.returncode: int | None = None
        self.wait_calls = 0

    def poll(self) -> int | None:
        """Return the current fake process status."""

        return self.returncode

    def wait(self, timeout=None) -> int:
        """Record reaping and return a killed-process status."""

        del timeout
        self.wait_calls += 1
        self.returncode = -9
        return self.returncode


class _Capture:
    """Capture double that closes its owned stream when finalized."""

    output_limited = False
    text = ""

    def __init__(self, stream: _TrackedStream, *, fail_join: bool = False) -> None:
        """Remember the owned stream and optional cleanup failure."""

        self.stream = stream
        self.fail_join = fail_join
        self.join_calls = 0

    def join(self, timeout=None) -> None:
        """Finalize the owned stream and optionally report a secondary error."""

        del timeout
        self.join_calls += 1
        self.stream.close()
        if self.fail_join:
            raise RuntimeError("secondary capture cleanup failure")


@pytest.mark.parametrize("failure_call", [1, 2])
def test_capture_startup_failure_kills_reaps_finalizes_and_closes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_call: int,
) -> None:
    """Either capture-start failure must leave no process, reader, or pipe alive."""

    process = _Process()
    killed: list[_Process] = []
    captures: list[_Capture] = []
    startup_calls = 0

    def fake_start(stream, **_kwargs):
        """Fail at the selected capture start and return earlier captures."""

        nonlocal startup_calls
        startup_calls += 1
        if startup_calls == failure_call:
            raise OSError("capture startup failed")
        capture = _Capture(cast(_TrackedStream, stream))
        captures.append(capture)
        return capture

    monkeypatch.setattr(bounded, "require_supported_platform", lambda: None)
    monkeypatch.setattr(bounded.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        bounded,
        "kill_process_group",
        lambda candidate: killed.append(cast(_Process, candidate)),
    )
    monkeypatch.setattr(bounded, "start_bounded_capture", fake_start)

    with pytest.raises(OSError, match="capture startup failed"):
        bounded.run_bounded_command(
            ["tool"],
            cwd=tmp_path,
            env={},
            timeout=10,
            evidence_limit_bytes=4096,
        )

    assert killed == [process]
    assert process.wait_calls == 1
    assert process.stdout.closed
    assert process.stderr.closed
    assert all(capture.join_calls == 2 for capture in captures)


def test_capture_startup_preserves_original_error_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Secondary join errors cannot replace the capture-start root cause."""

    process = _Process()
    capture = _Capture(process.stdout, fail_join=True)
    startup_calls = 0
    killed: list[object] = []

    def fake_start(_stream, **_kwargs):
        """Return stdout capture and fail while starting stderr capture."""

        nonlocal startup_calls
        startup_calls += 1
        if startup_calls == 1:
            return capture
        raise OSError("primary capture startup failure")

    monkeypatch.setattr(bounded, "require_supported_platform", lambda: None)
    monkeypatch.setattr(bounded.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        bounded,
        "kill_process_group",
        lambda candidate: killed.append(candidate),
    )
    monkeypatch.setattr(bounded, "start_bounded_capture", fake_start)

    with pytest.raises(OSError, match="primary capture startup failure"):
        bounded.run_bounded_command(
            ["tool"],
            cwd=tmp_path,
            env={},
            timeout=10,
            evidence_limit_bytes=4096,
        )

    assert killed == [process]
    assert process.wait_calls == 1
    assert capture.join_calls == 2
    assert process.stdout.closed
    assert process.stderr.closed

