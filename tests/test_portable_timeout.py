"""Checks for the stdlib timeout fallback used by local review tests."""

from __future__ import annotations

import importlib.util
import signal
import subprocess
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ci" / "portable_timeout.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("portable_timeout_under_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakeProcess:
    pid = 123

    def __init__(self, waits):
        self._waits = iter(waits)

    def wait(self, timeout=None):
        del timeout
        result = next(self._waits)
        if isinstance(result, BaseException):
            raise result
        return result


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


def test_helpers_cover_duration_validation_signals_and_termination(monkeypatch) -> None:
    module = _load_module()
    assert module._seconds("1.5s") == 1.5
    assert module._seconds("2") == 2.0
    with pytest.raises(ValueError, match="invalid duration"):
        module._seconds("tomorrow")

    signals = []
    monkeypatch.setattr(module.os, "killpg", lambda pid, signum: signals.append((pid, signum)))
    process = SimpleNamespace(pid=9)
    module._signal_process_group(process, signal.SIGTERM)
    assert signals == [(9, signal.SIGTERM)]

    def missing_process_group(_pid, _signum):
        raise ProcessLookupError

    monkeypatch.setattr(module.os, "killpg", missing_process_group)
    module._signal_process_group(process, signal.SIGTERM)

    immediate = _FakeProcess([7])
    assert module._terminate(immediate, 0.1) == 7

    killed = _FakeProcess(
        [subprocess.TimeoutExpired(["fake"], 0.1), 9]
    )
    assert module._terminate(killed, 0.1) == 9


def test_main_rejects_invalid_arguments_and_start_failure(monkeypatch, capsys) -> None:
    module = _load_module()
    assert module.main([]) == 2
    assert module.main(["1", "--", "echo"]) == 2
    assert module.main(["1", "2", "--"]) == 2
    assert module.main(["bad", "1", "--", "echo"]) == 2

    def cannot_start(*_args, **_kwargs):
        raise OSError("synthetic start failure")

    monkeypatch.setattr(module.subprocess, "Popen", cannot_start)
    assert module.main(["1", "1", "--", "echo"]) == 127
    assert "synthetic start failure" in capsys.readouterr().err


def test_main_zero_duration_and_signal_forwarding(monkeypatch) -> None:
    module = _load_module()
    process = _FakeProcess([17])
    handlers = {}
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(
        module.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )
    assert module.main(["1", "0", "--", "echo"]) == 17

    forwarded = []
    monkeypatch.setattr(
        module,
        "_signal_process_group",
        lambda target, signum: forwarded.append((target, signum)),
    )
    with pytest.raises(SystemExit, match="143"):
        handlers[signal.SIGTERM](signal.SIGTERM, None)
    assert forwarded == [(process, signal.SIGTERM)]


def test_main_waits_for_child_and_terminates_after_deadline(monkeypatch) -> None:
    module = _load_module()
    waiting = _FakeProcess(
        [subprocess.TimeoutExpired(["fake"], 1), 0]
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: waiting)
    monkeypatch.setattr(module.time, "monotonic", iter([0.0, 0.1, 0.2]).__next__)
    assert module.main(["1", "1", "--", "echo"]) == 0

    timed_out = _FakeProcess(
        [subprocess.TimeoutExpired(["fake"], 0.1), 9]
    )
    monkeypatch.setattr(module.subprocess, "Popen", lambda *_args, **_kwargs: timed_out)
    monkeypatch.setattr(module.time, "monotonic", iter([0.0, 2.0]).__next__)
    assert module.main(["0.1", "0.1", "--", "echo"]) == 124
