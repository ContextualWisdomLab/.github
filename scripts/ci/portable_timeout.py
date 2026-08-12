#!/usr/bin/env python3
"""Small stdlib-only timeout fallback for hosts without GNU coreutils."""

from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import time


_DURATION_RE = re.compile(r"^(?P<value>[0-9]+(?:\.[0-9]+)?)(?P<unit>s)?$")


def _seconds(value: str) -> float:
    """Parse a non-negative seconds value with an optional ``s`` suffix."""
    match = _DURATION_RE.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"invalid duration: {value!r}")
    return float(match.group("value"))


def _signal_process_group(process: subprocess.Popen[object], signum: int) -> None:
    """Forward a signal to the child session, tolerating an exited process."""
    try:
        os.killpg(process.pid, signum)
    except ProcessLookupError:
        pass


def _terminate(process: subprocess.Popen[object], kill_after: float) -> int:
    """Terminate a child session, escalating to SIGKILL after the grace period."""
    _signal_process_group(process, signal.SIGTERM)
    try:
        return process.wait(timeout=kill_after)
    except subprocess.TimeoutExpired:
        _signal_process_group(process, signal.SIGKILL)
        return process.wait()


def main(argv: list[str]) -> int:
    """Run a command with a bounded timeout and return 124 on expiry."""
    if "--" not in argv:
        print("portable_timeout.py requires -- before the command", file=sys.stderr)
        return 2
    delimiter = argv.index("--")
    if delimiter != 2 or delimiter == len(argv) - 1:
        print("portable_timeout.py requires kill-after, duration, and a command", file=sys.stderr)
        return 2
    try:
        kill_after = _seconds(argv[0])
        duration = _seconds(argv[1])
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        process = subprocess.Popen(
            argv[delimiter + 1 :],
            start_new_session=True,
        )
    except OSError as exc:
        print(f"portable timeout could not start command: {exc}", file=sys.stderr)
        return 127

    def forward(signum: int, _frame: object) -> None:
        """Forward termination to the child process group before exiting."""
        _signal_process_group(process, signum)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, forward)
    signal.signal(signal.SIGINT, forward)

    if duration == 0:
        return process.wait()

    deadline = time.monotonic() + duration
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate(process, kill_after)
            return 124
        try:
            return process.wait(timeout=min(remaining, 1.0))
        except subprocess.TimeoutExpired:
            continue


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess tests
    raise SystemExit(main(sys.argv[1:]))
