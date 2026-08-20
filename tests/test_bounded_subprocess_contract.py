"""Branch-complete contracts for bounded subprocess helpers and failures."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts.ci import bounded_subprocess as bounded


def test_read_limit_and_timeout_validation_reject_all_unsafe_types() -> None:
    """Private validators reject Boolean, nonnumeric, nonpositive, and huge values."""

    for value in [False, "2", 0, bounded.MAXIMUM_OUTPUT_LIMIT_BYTES + 1]:
        with pytest.raises(ValueError, match="maximum_bytes"):
            bounded._validate_read_limit(value)
    for value in [False, "1", 0, -1]:
        with pytest.raises(ValueError, match="timeout"):
            bounded._validated_timeout(value)


def test_supported_platform_requires_posix_killpg(monkeypatch) -> None:
    """POSIX naming without process-group termination still fails closed."""

    monkeypatch.setattr(bounded, "_process_groups_supported", lambda: False)
    with pytest.raises(bounded.OutputLimitUnsupportedError):
        bounded.require_supported_platform()


def test_capture_notifies_once_across_multiple_overflowing_chunks() -> None:
    """Repeated chunks beyond the ceiling retain a suffix but notify only once."""

    class ChunkStream:
        """Return one deterministic chunk for each background read."""

        def __init__(self) -> None:
            self.chunks = [b"a" * 3000, b"b" * 3000, b"c" * 1000, b""]

        def read(self, size: int) -> bytes:
            """Return the next chunk within the requested reader contract."""

            assert size == bounded.READ_CHUNK_BYTES
            return self.chunks.pop(0)

        def close(self) -> None:
            """Provide the binary-stream close interface."""

    notifications: list[str] = []
    capture = bounded.start_bounded_capture(
        ChunkStream(),  # type: ignore[arg-type]
        evidence_limit_bytes=4096,
        on_limit=lambda: notifications.append("limited"),
    )
    capture.join(timeout=5)

    assert notifications == ["limited"]
    assert capture.output_limited
    assert capture.total_bytes == 7000
    assert capture.text.endswith("c" * 1000)


def test_capture_destination_failures_propagate_without_masking_read_error(
    tmp_path: Path,
) -> None:
    """Evidence-write errors surface, while an earlier read error keeps precedence."""

    blocked_parent = tmp_path / "blocked"
    blocked_parent.write_text("not a directory", encoding="utf-8")
    destination = blocked_parent / "capture.log"

    capture = bounded.start_bounded_capture(
        io.BytesIO(b"safe"),
        evidence_limit_bytes=4096,
        on_limit=lambda: None,
        destination=destination,
    )
    with pytest.raises((FileExistsError, NotADirectoryError)):
        capture.join(timeout=5)

    class ReadFailure:
        """Fail before the destination writer also encounters its path error."""

        def read(self, size: int) -> bytes:
            """Raise the primary reader failure."""

            del size
            raise OSError("primary read failure")

        def close(self) -> None:
            """Provide the binary-stream close interface."""

    capture = bounded.start_bounded_capture(
        ReadFailure(),  # type: ignore[arg-type]
        evidence_limit_bytes=4096,
        on_limit=lambda: None,
        destination=destination,
    )
    with pytest.raises(OSError, match="primary read failure"):
        capture.join(timeout=5)


def test_command_normalization_rejects_empty_executable() -> None:
    """A present but empty executable token is not a runnable command."""

    with pytest.raises(ValueError, match="command"):
        bounded._normalized_command([""])


def test_kill_process_group_handles_finished_and_disappearing_processes(
    monkeypatch,
) -> None:
    """Termination is idempotent when a process already exited or disappeared."""

    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(
        bounded.os,
        "killpg",
        lambda pid, signal_number: calls.append((pid, signal_number)),
    )

    class FinishedProcess:
        """Represent one already-reaped child."""

        pid = 10

        def poll(self) -> int:
            """Return a completed status."""

            return 0

    bounded.kill_process_group(FinishedProcess())  # type: ignore[arg-type]
    assert calls == []

    class RunningProcess:
        """Represent one child that disappears before the signal is delivered."""

        pid = 11

        def poll(self):
            """Report an apparently running child."""

            return None

    def missing_process(pid: int, signal_number: int) -> None:
        """Simulate the race between poll and group signaling."""

        del pid, signal_number
        raise ProcessLookupError

    monkeypatch.setattr(bounded.os, "killpg", missing_process)
    bounded.kill_process_group(RunningProcess())  # type: ignore[arg-type]


def test_run_rejects_missing_subprocess_pipes(monkeypatch, tmp_path: Path) -> None:
    """A broken Popen contract is killed and rejected before reader creation."""

    class MissingPipesProcess:
        """Expose no stdout or stderr pipe despite the requested configuration."""

        pid = 12
        stdout = None
        stderr = None
        returncode = -9

        def poll(self):
            """Report a running child until the fake kill path executes."""

            return None

        def wait(self, timeout=None) -> int:
            """Return the fake terminal status."""

            del timeout
            return self.returncode

    process = MissingPipesProcess()
    monkeypatch.setattr(bounded, "require_supported_platform", lambda: None)
    monkeypatch.setattr(bounded.subprocess, "Popen", lambda *args, **kwargs: process)
    killed: list[object] = []
    monkeypatch.setattr(bounded, "kill_process_group", lambda candidate: killed.append(candidate))

    with pytest.raises(RuntimeError, match="pipes"):
        bounded.run_bounded_command(
            ["tool"],
            cwd=tmp_path,
            env={},
            timeout=1,
            evidence_limit_bytes=4096,
        )
    assert killed == [process]


def test_two_overflow_callbacks_kill_the_process_group_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Simultaneous stdout/stderr limit notifications share one kill transition."""

    callbacks: list[Callable[[], None]] = []

    class FakePipe:
        """Stand in for one requested subprocess pipe."""

    class FakeProcess:
        """Invoke both capture callbacks while the parent waits."""

        pid = 13
        stdout = FakePipe()
        stderr = FakePipe()
        returncode = -9

        def poll(self):
            """Report a running process during callback delivery."""

            return None

        def wait(self, timeout=None) -> int:
            """Deliver both overflow callbacks and return the terminal status."""

            del timeout
            if callbacks:
                callbacks[0]()
                callbacks[1]()
            return self.returncode

    class FakeCapture:
        """Return fixed limited evidence without background threads."""

        output_limited = True
        text = bounded.TRUNCATION_MARKER

        def join(self, timeout=None) -> None:
            """Complete immediately."""

            del timeout

    process = FakeProcess()
    monkeypatch.setattr(bounded, "require_supported_platform", lambda: None)
    monkeypatch.setattr(bounded.subprocess, "Popen", lambda *args, **kwargs: process)

    def fake_capture(stream, *, evidence_limit_bytes, on_limit, destination=None):
        """Record each overflow callback supplied by the command runner."""

        del stream, evidence_limit_bytes, destination
        callbacks.append(on_limit)
        return FakeCapture()

    monkeypatch.setattr(bounded, "start_bounded_capture", fake_capture)
    kills: list[object] = []
    monkeypatch.setattr(bounded, "kill_process_group", lambda candidate: kills.append(candidate))

    result = bounded.run_bounded_command(
        ["tool"],
        cwd=tmp_path,
        env={},
        timeout=1,
        evidence_limit_bytes=4096,
    )

    assert result.output_limited
    assert kills == [process]


def test_run_joins_both_stream_captures_when_one_join_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A reader failure cannot leave the sibling drain thread unjoined."""

    class FakePipe:
        """Stand in for one requested subprocess pipe."""

    class FakeProcess:
        """Complete immediately with both requested pipes present."""

        pid = 14
        stdout = FakePipe()
        stderr = FakePipe()
        returncode = 0

        def poll(self):
            """Return the completed status."""

            return self.returncode

        def wait(self, timeout=None) -> int:
            """Complete immediately."""

            del timeout
            return self.returncode

    joins: list[str] = []

    class FakeCapture:
        """Record join order and optionally raise one deterministic error."""

        output_limited = False
        text = ""

        def __init__(self, label: str, error: BaseException | None) -> None:
            self.label = label
            self.error = error

        def join(self, timeout=None) -> None:
            """Record finalization before surfacing the configured error."""

            del timeout
            joins.append(self.label)
            if self.error is not None:
                raise self.error

    captures = iter(
        [
            FakeCapture("stdout", OSError("stdout drain failed")),
            FakeCapture("stderr", None),
        ]
    )
    monkeypatch.setattr(bounded, "require_supported_platform", lambda: None)
    monkeypatch.setattr(
        bounded.subprocess,
        "Popen",
        lambda *args, **kwargs: FakeProcess(),
    )
    monkeypatch.setattr(
        bounded,
        "start_bounded_capture",
        lambda *args, **kwargs: next(captures),
    )

    with pytest.raises(OSError, match="stdout drain failed"):
        bounded.run_bounded_command(
            ["tool"],
            cwd=tmp_path,
            env={},
            timeout=1,
            evidence_limit_bytes=4096,
        )

    assert joins == ["stdout", "stderr"]
