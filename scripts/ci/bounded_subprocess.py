"""Run POSIX child processes with kernel-enforced bounded output files."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

try:
    import resource as _resource_module
except ImportError:  # pragma: no cover - exercised by injected unsupported state
    _resource_module = None


_resource: ModuleType | None = _resource_module

OUTPUT_LIMIT_EXIT_CODE = 123
DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES = 1_048_576
DEFAULT_SERVICE_LOG_LIMIT_BYTES = 4_194_304
MAXIMUM_OUTPUT_LIMIT_BYTES = 67_108_864
MINIMUM_OUTPUT_LIMIT_BYTES = 4_096
TRUNCATION_MARKER = "...[output truncated]...\n"


class OutputLimitUnsupportedError(RuntimeError):
    """Report that the operating system cannot enforce child file-size limits."""


@dataclass(frozen=True)
class BoundedText:
    """One bounded decoded file suffix and its original stored byte size."""

    text: str
    truncated: bool
    stored_bytes: int


@dataclass(frozen=True)
class BoundedCompletedProcess:
    """A completed child result whose output was bounded before decoding."""

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


def _require_resource_module() -> ModuleType:
    """Return the POSIX resource module or fail before child execution."""

    if (
        os.name != "posix"
        or _resource is None
        or not hasattr(_resource, "RLIMIT_FSIZE")
        or not hasattr(_resource, "RLIM_INFINITY")
    ):
        raise OutputLimitUnsupportedError(
            "POSIX RLIMIT_FSIZE support is required for bounded child output"
        )
    return _resource


def bounded_file_preexec(evidence_limit_bytes: int) -> Callable[[], None]:
    """Return a child-only callable that lowers the maximum writable file size."""

    evidence_limit = validate_output_limit(
        evidence_limit_bytes,
        "evidence output limit",
    )
    resource_module = _require_resource_module()
    kernel_limit = evidence_limit + 1

    def apply_limit() -> None:
        """Lower the child soft and hard file-size limits without raising either."""

        _soft_limit, hard_limit = resource_module.getrlimit(
            resource_module.RLIMIT_FSIZE
        )
        target_limit = (
            kernel_limit
            if hard_limit == resource_module.RLIM_INFINITY
            else min(kernel_limit, hard_limit)
        )
        resource_module.setrlimit(
            resource_module.RLIMIT_FSIZE,
            (target_limit, target_limit),
        )

    return apply_limit


def read_bounded_suffix(path: Path, maximum_bytes: int) -> BoundedText:
    """Read at most the final byte budget from one regular capture file."""

    read_limit = _validate_read_limit(maximum_bytes)
    stored_bytes = path.stat().st_size
    truncated = stored_bytes > read_limit
    with path.open("rb") as captured_file:
        if truncated:
            captured_file.seek(stored_bytes - read_limit)
        data = captured_file.read(read_limit)
    decoded = data.decode("utf-8", errors="replace")
    text = f"{TRUNCATION_MARKER}{decoded}" if truncated else decoded
    return BoundedText(
        text=text,
        truncated=truncated,
        stored_bytes=stored_bytes,
    )


def file_limit_reached(
    path: Path,
    evidence_limit_bytes: int,
    return_code: int | None,
) -> bool:
    """Return whether file size or SIGXFSZ proves an attempted output overflow."""

    evidence_limit = validate_output_limit(
        evidence_limit_bytes,
        "evidence output limit",
    )
    file_exceeded = path.stat().st_size > evidence_limit
    file_size_signal = getattr(signal, "SIGXFSZ", None)
    signal_exceeded = (
        file_size_signal is not None
        and return_code == -int(file_size_signal)
    )
    return file_exceeded or signal_exceeded


def _normalized_command(arguments: Sequence[object]) -> tuple[str, ...]:
    """Return one non-empty immutable structured command."""

    command = tuple(str(argument) for argument in arguments)
    if not command or not command[0]:
        raise ValueError("command must contain one executable")
    return command


def _validated_timeout(timeout: object) -> int | float:
    """Return one positive numeric subprocess timeout."""

    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or timeout <= 0
    ):
        raise ValueError("timeout must be a positive number")
    return timeout


def run_bounded_command(
    arguments: Sequence[object],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: int | float,
    evidence_limit_bytes: int,
) -> BoundedCompletedProcess:
    """Run a structured command with bounded private stdout and stderr files."""

    command = _normalized_command(arguments)
    timeout_seconds = _validated_timeout(timeout)
    evidence_limit = validate_output_limit(
        evidence_limit_bytes,
        "evidence output limit",
    )
    preexec_function = bounded_file_preexec(evidence_limit)

    with tempfile.TemporaryDirectory(prefix="bounded-subprocess-") as capture_root:
        capture_directory = Path(capture_root)
        stdout_path = capture_directory / "stdout.log"
        stderr_path = capture_directory / "stderr.log"
        completed: subprocess.CompletedProcess[bytes] | None = None
        timeout_error: subprocess.TimeoutExpired | None = None
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            try:
                completed = subprocess.run(
                    list(command),
                    cwd=cwd,
                    env=dict(env),
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=timeout_seconds,
                    check=False,
                    shell=False,
                    preexec_fn=preexec_function,
                )
            except subprocess.TimeoutExpired as error:
                timeout_error = error

        return_code = completed.returncode if completed is not None else None
        stdout = read_bounded_suffix(stdout_path, evidence_limit)
        stderr = read_bounded_suffix(stderr_path, evidence_limit)
        output_limited = file_limit_reached(
            stdout_path,
            evidence_limit,
            return_code,
        ) or file_limit_reached(
            stderr_path,
            evidence_limit,
            return_code,
        )
        if timeout_error is not None:
            raise BoundedTimeoutExpired(
                command,
                timeout_seconds,
                stdout=stdout.text,
                stderr=stderr.text,
                output_limited=output_limited,
            ) from timeout_error
        if completed is None:  # pragma: no cover - defensive subprocess invariant
            raise RuntimeError("subprocess returned neither completion nor timeout")
        return BoundedCompletedProcess(
            args=command,
            returncode=completed.returncode,
            stdout=stdout.text,
            stderr=stderr.text,
            output_limited=output_limited,
        )
