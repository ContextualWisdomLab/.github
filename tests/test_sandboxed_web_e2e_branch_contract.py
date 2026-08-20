"""Branch-complete contracts for bounded sandbox web E2E orchestration."""

from __future__ import annotations

import json
import subprocess
import urllib.error
from pathlib import Path
from typing import cast

import pytest

from scripts.ci import bounded_subprocess as bounded
from scripts.ci import sandboxed_web_e2e


def _result(output: str) -> dict[str, object]:
    """Parse one final web E2E result marker."""

    marker = f"{sandboxed_web_e2e.RESULT_MARKER} "
    line = next(line for line in output.splitlines() if line.startswith(marker))
    return json.loads(line.removeprefix(marker))


class _DoneProcess:
    """Minimal process double that has already completed."""

    pid = 100
    returncode = 0

    def poll(self) -> int:
        """Return the completed status."""

        return self.returncode

    def wait(self, timeout=None) -> int:
        """Return immediately."""

        del timeout
        return self.returncode


class _RunningProcess:
    """Minimal running process double for cleanup branches."""

    pid = 101
    returncode = None

    def poll(self):
        """Report that the process remains active."""

        return self.returncode

    def wait(self, timeout=None) -> int:
        """Complete when the fake process is explicitly waited."""

        del timeout
        self.returncode = 0
        return 0


def _service(tmp_path: Path, *, process=None, log_limit_bytes: int = 4096):
    """Create one service double with no background capture."""

    return sandboxed_web_e2e.Service(
        label="service",
        command="service",
        process=cast(subprocess.Popen[bytes], process or _DoneProcess()),
        log_path=tmp_path / "service.log",
        log_limit_bytes=log_limit_bytes,
    )


def test_start_service_rejects_missing_output_pipe(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """A broken Popen pipe contract is killed and rejected."""

    class MissingPipeProcess(_RunningProcess):
        """Return no stdout despite the requested PIPE configuration."""

        stdout = None

    process = MissingPipeProcess()
    monkeypatch.setattr(bounded, "require_supported_platform", lambda: None)
    monkeypatch.setattr(
        sandboxed_web_e2e.subprocess,
        "Popen",
        lambda *args, **kwargs: process,
    )
    killed: list[object] = []
    monkeypatch.setattr(
        bounded,
        "kill_process_group",
        lambda candidate: killed.append(candidate),
    )

    with pytest.raises(RuntimeError, match="pipe"):
        sandboxed_web_e2e.start_service(
            "backend",
            "tool",
            tmp_path,
            {},
            tmp_path,
            4096,
        )
    assert killed == [process]


def test_service_limit_fallback_handles_missing_small_and_large_files(
    tmp_path: Path,
) -> None:
    """Legacy/fake services classify file-only evidence deterministically."""

    service = _service(tmp_path)
    assert not sandboxed_web_e2e.service_output_limited(service)
    service.log_path.write_bytes(b"safe")
    assert not sandboxed_web_e2e.service_output_limited(service)
    service.log_path.write_bytes(b"x" * 4096)
    assert not sandboxed_web_e2e.service_output_limited(service)
    service.log_path.write_bytes(b"x" * 4097)
    assert sandboxed_web_e2e.service_output_limited(service)


def test_wait_for_url_handles_empty_invalid_exited_limited_and_success(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Readiness polling preserves every validation and termination branch."""

    service = _service(tmp_path)
    assert sandboxed_web_e2e.wait_for_url("", 1, service)
    with pytest.raises(ValueError, match="http"):
        sandboxed_web_e2e.wait_for_url("file:///tmp/ready", 1, service)
    assert not sandboxed_web_e2e.wait_for_url(
        "https://example.invalid/ready",
        1,
        service,
    )

    running = _service(tmp_path, process=_RunningProcess())
    running.log_path.write_bytes(b"x" * 4097)
    assert not sandboxed_web_e2e.wait_for_url(
        "https://example.invalid/ready",
        1,
        running,
    )
    running.log_path.unlink()

    class Response:
        """Context-managed readiness response."""

        status = 204

        def __enter__(self):
            """Return the response."""

            return self

        def __exit__(self, exc_type, exc, traceback) -> None:
            """Close without suppressing exceptions."""

            del exc_type, exc, traceback

    class Opener:
        """Return one successful response."""

        def open(self, url: str, timeout: int):
            """Validate the poll request and return readiness."""

            assert url == "https://ready.example/health"
            assert timeout == 2
            return Response()

    clean_running = _service(tmp_path, process=_RunningProcess())
    monkeypatch.setattr(
        sandboxed_web_e2e.urllib.request,
        "build_opener",
        lambda handler: Opener(),
    )
    assert sandboxed_web_e2e.wait_for_url(
        "https://ready.example/health",
        1,
        clean_running,
    )


def test_wait_for_url_retries_url_errors_until_deadline(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Transient URL errors sleep and eventually produce a bounded false result."""

    class FailingOpener:
        """Raise one deterministic URL error per poll."""

        def open(self, url: str, timeout: int):
            """Reject the readiness request."""

            del url, timeout
            raise urllib.error.URLError("not ready")

    timeline = iter([0.0, 0.0, 2.0])
    sleeps: list[int] = []
    monkeypatch.setattr(sandboxed_web_e2e.time, "monotonic", lambda: next(timeline))
    monkeypatch.setattr(sandboxed_web_e2e.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(
        sandboxed_web_e2e.urllib.request,
        "build_opener",
        lambda handler: FailingOpener(),
    )

    assert not sandboxed_web_e2e.wait_for_url(
        "https://ready.example/health",
        1,
        _service(tmp_path, process=_RunningProcess()),
    )
    assert sleeps == [1]


def test_redirect_handler_raises_http_error() -> None:
    """Readiness redirects are never followed."""

    handler = sandboxed_web_e2e.NoRedirectHandler()
    request = type("Request", (), {"full_url": "https://ready.example"})()
    with pytest.raises(urllib.error.HTTPError):
        handler.redirect_request(request, None, 302, "redirect", {}, "https://other")


def test_stop_service_handles_finished_lookup_race_timeout_and_capture(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Cleanup covers normal, disappearing, force-kill, and capture-finalization paths."""

    joined: list[float | None] = []

    class Capture:
        """Record finalization of one fake background drain."""

        output_limited = False

        def join(self, timeout=None) -> None:
            """Record the requested join timeout."""

            joined.append(timeout)

    finished = _service(tmp_path)
    finished.capture = cast(bounded.BoundedOutputCapture, Capture())
    sandboxed_web_e2e.stop_service(finished)
    assert joined == [10]

    disappearing = _service(tmp_path, process=_RunningProcess())
    monkeypatch.setattr(
        sandboxed_web_e2e.os,
        "killpg",
        lambda pid, signal_number: (_ for _ in ()).throw(ProcessLookupError()),
    )
    sandboxed_web_e2e.stop_service(disappearing)

    class TimeoutProcess(_RunningProcess):
        """Timeout once before completing after force kill."""

        def __init__(self) -> None:
            self.waits = 0

        def wait(self, timeout=None) -> int:
            """Raise once, then return the terminal status."""

            del timeout
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("service", 10)
            self.returncode = -9
            return self.returncode

    timeout_process = TimeoutProcess()
    timed = _service(tmp_path, process=timeout_process)
    monkeypatch.setattr(sandboxed_web_e2e.os, "killpg", lambda pid, sig: None)
    forced: list[object] = []
    monkeypatch.setattr(
        bounded,
        "kill_process_group",
        lambda process: forced.append(process),
    )
    sandboxed_web_e2e.stop_service(timed)
    assert forced == [timeout_process]


def test_tail_text_rejects_nonpositive_line_count(tmp_path: Path) -> None:
    """A caller cannot request an ambiguous or unbounded line selection."""

    log_path = tmp_path / "service.log"
    log_path.write_text("line\n", encoding="utf-8")
    with pytest.raises(ValueError, match="max_lines"):
        sandboxed_web_e2e.tail_text(log_path, max_lines=0)


def test_tail_text_validates_line_count_before_missing_file(tmp_path: Path) -> None:
    """A missing evidence file cannot bypass the configured line-budget contract."""

    with pytest.raises(ValueError, match="max_lines"):
        sandboxed_web_e2e.tail_text(tmp_path / "missing.log", max_lines=0)


def test_timeout_precedence_survives_limited_partial_output(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """A timed-out E2E remains 124 even when its bounded stream was truncated."""

    repository = tmp_path / "repository"
    repository.mkdir()

    def fake_start(label, command, cwd, env, logs_dir, log_limit_bytes):
        """Return already-running service doubles without real children."""

        del command, cwd, env
        return sandboxed_web_e2e.Service(
            label=label,
            command=label,
            process=cast(subprocess.Popen[bytes], _RunningProcess()),
            log_path=logs_dir / f"{label}.log",
            log_limit_bytes=log_limit_bytes,
        )

    def timeout_run(command, cwd, env, timeout, output_limit_bytes):
        """Raise bounded timeout evidence."""

        del command, cwd, env, output_limit_bytes
        raise bounded.BoundedTimeoutExpired(
            ["e2e"],
            timeout,
            stdout=bounded.TRUNCATION_MARKER,
            stderr="",
            output_limited=True,
        )

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *args: True)
    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", timeout_run)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: None)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repository),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
            "--e2e-timeout",
            "1",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 124
    assert "timed out after 1s" in captured.err
    assert _result(captured.out)["output_limited"] is True


def test_capture_finalization_failure_maps_to_resource_exit(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """A service capture failure cannot leave a successful result envelope."""

    repository = tmp_path / "repository"
    repository.mkdir()

    def fake_start(label, command, cwd, env, logs_dir, log_limit_bytes):
        """Return completed service doubles."""

        del command, cwd, env
        return sandboxed_web_e2e.Service(
            label=label,
            command=label,
            process=cast(subprocess.Popen[bytes], _DoneProcess()),
            log_path=logs_dir / f"{label}.log",
            log_limit_bytes=log_limit_bytes,
        )

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *args: True)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda *args: bounded.BoundedCompletedProcess(
            args=("e2e",),
            returncode=0,
            stdout="",
            stderr="",
            output_limited=False,
        ),
    )
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "stop_service",
        lambda service: (_ for _ in ()).throw(RuntimeError("capture failed")),
    )
    forced: list[object] = []
    monkeypatch.setattr(
        bounded,
        "kill_process_group",
        lambda process: forced.append(process),
    )

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repository),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
    assert "bounded service capture failed" in captured.err
    assert _result(captured.out)["output_limited"] is True
    assert len(forced) == 2


def test_timeout_precedence_survives_cleanup_and_late_service_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Timeout 124 remains authoritative through late capture failures and overflow."""
    repository = tmp_path / "repository"
    repository.mkdir()

    def fake_start(label, command, cwd, env, logs_dir, log_limit_bytes):
        del command, cwd, env
        return sandboxed_web_e2e.Service(
            label=label,
            command=label,
            process=cast(subprocess.Popen[bytes], _DoneProcess()),
            log_path=logs_dir / f"{label}.log",
            log_limit_bytes=log_limit_bytes,
        )

    def timeout_run(*args):
        del args
        raise subprocess.TimeoutExpired(["e2e"], 1)

    limit_checks = iter([False, True])
    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *args: True)
    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", timeout_run)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "stop_service",
        lambda service: (_ for _ in ()).throw(RuntimeError(service.label)),
    )
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "_services_output_limited",
        lambda services: next(limit_checks),
    )

    assert sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repository),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
            "--e2e-timeout",
            "1",
        ]
    ) == 124
