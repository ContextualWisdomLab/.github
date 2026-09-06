"""Run POSIX child processes with continuously drained bounded output pipes."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


OUTPUT_LIMIT_EXIT_CODE = 123
DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES = 1_048_576
DEFAULT_SERVICE_LOG_LIMIT_BYTES = 4_194_304
MAXIMUM_OUTPUT_LIMIT_BYTES = 67_108_864
MINIMUM_OUTPUT_LIMIT_BYTES = 4_096
READ_CHUNK_BYTES = 65_536
READER_JOIN_TIMEOUT_SECONDS = 30.0
TRUNCATION_MARKER = "...[output truncated]...\n"


class OutputLimitUnsupportedError(RuntimeError):
    """Report that the operating system cannot isolate a child process group."""


@dataclass(frozen=True)
class BoundedText:
    """One bounded decoded file suffix and its original stored byte size."""

    text: str
    truncated: bool
    stored_bytes: int


@dataclass(frozen=True)
class BoundedCompletedProcess:
    """A completed child result whose output was drained into bounded buffers."""

    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    output_limited: bool


class BoundedTimeoutExpired(subprocess.TimeoutExpired):
    """A subprocess timeout carrying only bounded stdout and stderr evidence."""

    def __init__(
        self,
        command: Sequence[str],
        timeout: int | float,
        *,
        stdout: str,
        stderr: str,
        output_limited: bool,
    ) -> None:
        """Create timeout evidence with stable text stream attributes."""

        super().__init__(tuple(command), timeout, output=stdout, stderr=stderr)
        self.output_limited = output_limited


def validate_output_limit(value: object, label: str) -> int:
    """Return one configured output budget inside the supported safety range."""

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < MINIMUM_OUTPUT_LIMIT_BYTES
        or value > MAXIMUM_OUTPUT_LIMIT_BYTES
    ):
        raise ValueError(
            f"{label} must be an integer from {MINIMUM_OUTPUT_LIMIT_BYTES} "
            f"through {MAXIMUM_OUTPUT_LIMIT_BYTES}"
        )
    return value


def _validate_read_limit(value: object) -> int:
    """Return one positive bounded suffix-read size."""

    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
        or value > MAXIMUM_OUTPUT_LIMIT_BYTES
    ):
        raise ValueError(
            "maximum_bytes must be a positive integer no greater than "
            f"{MAXIMUM_OUTPUT_LIMIT_BYTES}"
        )
    return value


def _process_groups_supported() -> bool:
    """Return whether isolated POSIX process-group termination is available."""

    return os.name == "posix" and hasattr(os, "killpg")


def require_supported_platform() -> None:
    """Fail before execution when process-group termination is unavailable."""

    if not _process_groups_supported():
        raise OutputLimitUnsupportedError(
            "POSIX process-group support is required for bounded child output"
        )


def _render_bounded_bytes(buffer: bytes, limit: int, truncated: bool) -> bytes:
    """Return evidence bytes no larger than the configured stream budget."""

    if not truncated:
        return buffer[-limit:]
    marker = TRUNCATION_MARKER.encode("utf-8")
    if limit <= len(marker):
        return marker[:limit]
    suffix_budget = limit - len(marker)
    suffix = buffer[-suffix_budget:]
    return marker + suffix


def _decode_bounded_bytes(buffer: bytes, limit: int) -> str:
    """Decode evidence without expanding beyond its retained UTF-8 byte budget."""

    decoded = buffer.decode("utf-8", errors="replace")
    encoded = decoded.encode("utf-8")
    if len(encoded) <= limit:
        return decoded

    marker = TRUNCATION_MARKER if buffer.startswith(
        TRUNCATION_MARKER.encode("utf-8")
    ) else ""
    suffix_budget = limit - len(marker.encode("utf-8"))
    suffix = encoded[-suffix_budget:]
    return marker + suffix.decode("utf-8", errors="ignore")


class BoundedOutputCapture:
    """Continuously drain one binary pipe into a bounded final-suffix buffer."""

    def __init__(
        self,
        stream: BinaryIO,
        *,
        evidence_limit_bytes: int,
        on_limit: Callable[[], None],
        destination: Path | None = None,
    ) -> None:
        """Start one background drain with an optional bounded evidence file."""

        self._stream = stream
        self._limit = validate_output_limit(
            evidence_limit_bytes,
            "evidence output limit",
        )
        self._on_limit = on_limit
        self._destination = destination
        self._buffer = bytearray()
        self._total_bytes = 0
        self._output_limited = False
        self._error: BaseException | None = None
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._drain,
            name="bounded-output-drain",
            daemon=True,
        )
        self._thread.start()

    @property
    def stream(self) -> BinaryIO:
        """Return the binary stream owned by this background capture."""
        return self._stream

    @property
    def output_limited(self) -> bool:
        """Return whether this stream exceeded its configured byte budget."""

        with self._lock:
            return self._output_limited

    @property
    def total_bytes(self) -> int:
        """Return the complete byte count observed while draining the stream."""

        with self._lock:
            return self._total_bytes

    @property
    def text(self) -> str:
        """Return the bounded final suffix decoded with replacement semantics."""

        with self._lock:
            evidence = _render_bounded_bytes(
                bytes(self._buffer),
                self._limit,
                self._output_limited,
            )
        return _decode_bounded_bytes(evidence, self._limit)

    def _append(self, chunk: bytes) -> bool:
        """Append one chunk and report the first transition into limited state."""

        should_notify = False
        with self._lock:
            self._total_bytes += len(chunk)
            self._buffer.extend(chunk)
            overflow = len(self._buffer) - self._limit
            if overflow > 0:
                del self._buffer[:overflow]
            if self._total_bytes > self._limit and not self._output_limited:
                self._output_limited = True
                should_notify = True
        return should_notify

    def _write_destination(self) -> None:
        """Write at most the configured evidence budget to the destination file."""

        if self._destination is None:
            return
        self._destination.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            evidence = _render_bounded_bytes(
                bytes(self._buffer),
                self._limit,
                self._output_limited,
            )
        self._destination.write_bytes(evidence)

    def _drain(self) -> None:
        """Drain until EOF, killing the child once on the first byte overflow."""

        try:
            while True:
                chunk = self._stream.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                if self._append(chunk):
                    self._on_limit()
        except BaseException as error:  # noqa: BLE001 - propagated by join()
            self._error = error
        finally:
            try:
                self._stream.close()
                self._write_destination()
            except BaseException as error:  # noqa: BLE001 - propagated by join()
                if self._error is None:
                    self._error = error

    def join(self, timeout: float | None = None) -> None:
        """Wait for EOF and re-raise any background capture failure."""

        self._thread.join(timeout)
        if self._thread.is_alive():
            raise RuntimeError("bounded output drain did not finish")
        if self._error is not None:
            raise self._error


def start_bounded_capture(
    stream: BinaryIO,
    *,
    evidence_limit_bytes: int,
    on_limit: Callable[[], None],
    destination: Path | None = None,
) -> BoundedOutputCapture:
    """Start one bounded background drain for a binary subprocess stream."""

    return BoundedOutputCapture(
        stream,
        evidence_limit_bytes=evidence_limit_bytes,
        on_limit=on_limit,
        destination=destination,
    )


def read_bounded_suffix(path: Path, maximum_bytes: int) -> BoundedText:
    """Read at most the final byte budget from one regular evidence file."""

    read_limit = _validate_read_limit(maximum_bytes)
    stored_bytes = path.stat().st_size
    truncated = stored_bytes > read_limit
    with path.open("rb") as captured_file:
        if truncated:
            captured_file.seek(stored_bytes - read_limit)
        data = captured_file.read(read_limit)
    evidence = _render_bounded_bytes(data, read_limit, truncated)
    text = _decode_bounded_bytes(evidence, read_limit)
    return BoundedText(
        text=text,
        truncated=truncated,
        stored_bytes=stored_bytes,
    )


def _normalized_command(arguments: Sequence[object]) -> tuple[str, ...]:
    """Return one non-empty immutable structured command."""

    command = tuple(str(argument) for argument in arguments)
    if not command or not command[0]:
        raise ValueError("command must contain one executable")
    return command


def _validated_timeout(timeout: object) -> int | float:
    """Return one positive finite numeric subprocess timeout.

    Rejects ``bool``, non-numeric values, non-positive numbers, ``NaN``, and
    either signed infinity: none of those can ever reach the timeout/cleanup
    path, so a command given one of them would otherwise run unbounded.
    """

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
        or not math.isfinite(timeout)
    ):
        raise ValueError("timeout must be a positive number")
    return timeout


def kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Kill an isolated group, including descendants after its leader exits."""

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return


def _join_captures(
    captures: Sequence[BoundedOutputCapture],
    timeout: float = READER_JOIN_TIMEOUT_SECONDS,
) -> None:
    """Finalize every stream reader within one finite per-reader deadline."""

    first_error: BaseException | None = None
    for capture in captures:
        try:
            capture.join(timeout)
        except BaseException as error:  # noqa: BLE001 - re-raised after sibling join
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error


def _cleanup_capture_startup_failure(
    process: subprocess.Popen[bytes],
    captures: Sequence[BoundedOutputCapture],
    streams: Sequence[BinaryIO],
) -> None:
    """Best-effort terminate, reap, finalize, and close partial startup state."""

    with suppress(BaseException):
        kill_process_group(process)
    with suppress(BaseException):
        process.wait(timeout=10)
    for capture in captures:
        with suppress(BaseException):
            capture.join(timeout=10)
    owned_streams = {id(capture.stream) for capture in captures}
    for stream in streams:
        if id(stream) in owned_streams:
            continue
        with suppress(BaseException):
            stream.close()
    for capture in captures:
        with suppress(BaseException):
            capture.join(timeout=10)


def run_bounded_command(
    arguments: Sequence[object],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int | float,
    evidence_limit_bytes: int,
) -> BoundedCompletedProcess:
    """Run a structured command while continuously draining bounded pipe suffixes."""

    require_supported_platform()
    command = _normalized_command(arguments)
    timeout_seconds = _validated_timeout(timeout)
    evidence_limit = validate_output_limit(
        evidence_limit_bytes,
        "evidence output limit",
    )
    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(env),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
        shell=False,
        start_new_session=True,
    )
    if process.stdout is None or process.stderr is None:
        kill_process_group(process)
        process.wait()
        raise RuntimeError("subprocess pipes were not created")

    limit_triggered = threading.Event()

    def stop_for_limit() -> None:
        """Kill the process group only for the first overflowing stream."""

        if not limit_triggered.is_set():
            limit_triggered.set()
            kill_process_group(process)

    captures: list[BoundedOutputCapture] = []
    streams = (process.stdout, process.stderr)
    try:
        stdout_capture = start_bounded_capture(
            process.stdout,
            evidence_limit_bytes=evidence_limit,
            on_limit=stop_for_limit,
        )
        captures.append(stdout_capture)
        stderr_capture = start_bounded_capture(
            process.stderr,
            evidence_limit_bytes=evidence_limit,
            on_limit=stop_for_limit,
        )
        captures.append(stderr_capture)
    except BaseException:  # noqa: BLE001 - preserve the startup root cause
        _cleanup_capture_startup_failure(process, captures, streams)
        raise
    timed_out = False
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_process_group(process)
        process.wait()

    kill_process_group(process)

    _join_captures((stdout_capture, stderr_capture))
    output_limited = (
        stdout_capture.output_limited or stderr_capture.output_limited
    )
    if timed_out:
        raise BoundedTimeoutExpired(
            command,
            timeout_seconds,
            stdout=stdout_capture.text,
            stderr=stderr_capture.text,
            output_limited=output_limited,
        )
    return BoundedCompletedProcess(
        args=command,
        returncode=process.returncode,
        stdout=stdout_capture.text,
        stderr=stderr_capture.text,
        output_limited=output_limited,
    )
