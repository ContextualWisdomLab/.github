"""Fail-first regressions for credential-shaped sandbox subprocess evidence."""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from scripts.ci import sandboxed_verify, sandboxed_web_e2e


GITHUB_TOKEN = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890"
PASSWORD = "correct-horse-battery-staple"
SESSION_KEY = "session-value-should-not-leak"


def _bind_verify_workspace(monkeypatch, tmp_path) -> None:
    """Avoid filesystem-copy behavior while exercising the verification output boundary."""
    monkeypatch.setattr(sandboxed_verify, "copy_workspace", lambda *_args: tmp_path)
    monkeypatch.setattr(sandboxed_verify, "scrubbed_env", lambda *_args: {})


def _service(log_path):
    """Return a minimal running service fixture accepted by the E2E wrapper."""
    process = SimpleNamespace(poll=lambda: None, pid=12345, wait=lambda timeout: None)
    return sandboxed_web_e2e.Service("service", "serve", process, log_path)


def _bind_e2e_services(monkeypatch, tmp_path, *, log_text: str = "ordinary service log\n") -> None:
    """Bind deterministic ready services whose log evidence is controlled by the test."""
    counter = {"value": 0}

    def start_service(label, _command, _cwd, _env, logs_dir):
        counter["value"] += 1
        log_path = logs_dir / f"{label}-{counter['value']}.log"
        log_path.write_text(log_text, encoding="utf-8")
        return _service(log_path)

    monkeypatch.setattr(sandboxed_verify, "copy_workspace", lambda *_args: tmp_path)
    monkeypatch.setattr(sandboxed_verify, "scrubbed_env", lambda *_args: {})
    monkeypatch.setattr(sandboxed_web_e2e, "start_service", start_service)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *_args: True)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda _service: None)


def test_sandboxed_verify_redacts_completed_stdout_and_stderr(monkeypatch, tmp_path, capsys):
    """Completed verification output must cross the shared credential-redaction boundary."""
    _bind_verify_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sandboxed_verify,
        "run_command",
        lambda *_args: subprocess.CompletedProcess(
            args=["fake"],
            returncode=0,
            stdout=f"token={GITHUB_TOKEN}\nordinary stdout\n",
            stderr=f"password={PASSWORD}\nordinary stderr\n",
        ),
    )

    assert sandboxed_verify.main(["--repo-root", str(tmp_path), "--", "fake"]) == 0
    captured = capsys.readouterr()

    assert GITHUB_TOKEN not in captured.out
    assert PASSWORD not in captured.err
    assert "[REDACTED]" in captured.out
    assert "[REDACTED]" in captured.err
    assert "ordinary stdout" in captured.out
    assert "ordinary stderr" in captured.err


def test_sandboxed_verify_redacts_timeout_bytes(monkeypatch, tmp_path, capsys):
    """Timeout byte streams must be decoded and redacted before becoming CI evidence."""
    _bind_verify_workspace(monkeypatch, tmp_path)

    def timeout(*_args):
        raise subprocess.TimeoutExpired(
            cmd=["fake"],
            timeout=1,
            output=f"api_key={GITHUB_TOKEN}\nordinary timeout stdout\n".encode(),
            stderr=f"session_key={SESSION_KEY}\nordinary timeout stderr\n".encode(),
        )

    monkeypatch.setattr(sandboxed_verify, "run_command", timeout)

    assert sandboxed_verify.main(["--repo-root", str(tmp_path), "--timeout", "1", "--", "fake"]) == 124
    captured = capsys.readouterr()

    assert GITHUB_TOKEN not in captured.out
    assert SESSION_KEY not in captured.err
    assert "[REDACTED]" in captured.out
    assert "[REDACTED]" in captured.err
    assert "ordinary timeout stdout" in captured.out
    assert "ordinary timeout stderr" in captured.err


def test_sandboxed_verify_timeout_without_captured_streams(monkeypatch, tmp_path, capsys):
    """A timeout with no captured streams preserves the empty-output branches."""
    _bind_verify_workspace(monkeypatch, tmp_path)

    def timeout(*_args):
        raise subprocess.TimeoutExpired(cmd=["fake"], timeout=1, output=None, stderr=None)

    monkeypatch.setattr(sandboxed_verify, "run_command", timeout)

    assert sandboxed_verify.main(["--repo-root", str(tmp_path), "--timeout", "1", "--", "fake"]) == 124
    captured = capsys.readouterr()

    assert "[REDACTED]" not in captured.out
    assert "command timed out after 1s" in captured.err


def test_sandboxed_verify_handles_empty_completed_streams(monkeypatch, tmp_path, capsys):
    """Redaction does not invent output when a completed command emits no streams."""
    _bind_verify_workspace(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sandboxed_verify,
        "run_command",
        lambda *_args: subprocess.CompletedProcess(
            args=["fake"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    assert sandboxed_verify.main(["--repo-root", str(tmp_path), "--", "fake"]) == 0
    captured = capsys.readouterr()

    assert "[REDACTED]" not in captured.out
    assert captured.err == ""


def test_sandboxed_verify_redacts_explicit_allow_env_value(monkeypatch, tmp_path, capsys):
    """An opaque explicitly allowed environment value never becomes completed-process evidence."""
    env_name = "CWL_TEST_CREDENTIAL"
    env_value = "opaque-allow-env-fixture-123456"
    monkeypatch.setattr(sandboxed_verify, "copy_workspace", lambda *_args: tmp_path)
    monkeypatch.setattr(sandboxed_verify, "scrubbed_env", lambda *_args: {env_name: env_value})

    def completed(_command, _cwd, env, _timeout):
        assert env[env_name] == env_value
        return subprocess.CompletedProcess(
            args=["fake"],
            returncode=0,
            stdout=f"ordinary stdout {env_value}\n",
            stderr=f"ordinary stderr {env_value}\n",
        )

    monkeypatch.setattr(sandboxed_verify, "run_command", completed)

    assert (
        sandboxed_verify.main(
            ["--repo-root", str(tmp_path), "--allow-env", env_name, "--", "fake"]
        )
        == 0
    )
    captured = capsys.readouterr()

    assert env_value not in captured.out
    assert env_value not in captured.err
    assert "ordinary stdout" in captured.out
    assert "ordinary stderr" in captured.err


def test_sandboxed_verify_redacts_explicit_allow_env_value_on_timeout(
    monkeypatch, tmp_path, capsys
):
    """An opaque explicitly allowed environment value never becomes timeout evidence."""
    env_name = "CWL_TEST_CREDENTIAL"
    env_value = "opaque-timeout-env-fixture-123456"
    monkeypatch.setattr(sandboxed_verify, "copy_workspace", lambda *_args: tmp_path)
    monkeypatch.setattr(sandboxed_verify, "scrubbed_env", lambda *_args: {env_name: env_value})

    def timeout(_command, _cwd, env, timeout_seconds):
        assert env[env_name] == env_value
        raise subprocess.TimeoutExpired(
            cmd=["fake"],
            timeout=timeout_seconds,
            output=f"ordinary timeout stdout {env_value}\n".encode(),
            stderr=f"ordinary timeout stderr {env_value}\n".encode(),
        )

    monkeypatch.setattr(sandboxed_verify, "run_command", timeout)

    assert (
        sandboxed_verify.main(
            [
                "--repo-root",
                str(tmp_path),
                "--timeout",
                "1",
                "--allow-env",
                env_name,
                "--",
                "fake",
            ]
        )
        == 124
    )
    captured = capsys.readouterr()

    assert env_value not in captured.out
    assert env_value not in captured.err
    assert "ordinary timeout stdout" in captured.out
    assert "ordinary timeout stderr" in captured.err


def test_sandboxed_web_e2e_redacts_completed_output_and_service_tails(monkeypatch, tmp_path, capsys):
    """E2E process streams and backend/frontend log tails must redact credentials."""
    _bind_e2e_services(
        monkeypatch,
        tmp_path,
        log_text=f"credential={GITHUB_TOKEN}\nordinary service log\n",
    )
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda *_args: subprocess.CompletedProcess(
            args=["fake-e2e"],
            returncode=0,
            stdout=f"authorization=Bearer {GITHUB_TOKEN}\nordinary e2e stdout\n",
            stderr=f"password={PASSWORD}\nordinary e2e stderr\n",
        ),
    )

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(tmp_path),
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()

    assert GITHUB_TOKEN not in captured.out
    assert PASSWORD not in captured.err
    assert captured.out.count("[REDACTED]") >= 3
    assert "[REDACTED]" in captured.err
    assert "ordinary e2e stdout" in captured.out
    assert "ordinary service log" in captured.out
    assert "ordinary e2e stderr" in captured.err


def test_sandboxed_web_e2e_redacts_timeout_bytes(monkeypatch, tmp_path, capsys):
    """E2E timeout stdout/stderr bytes must be redacted without changing timeout semantics."""
    _bind_e2e_services(monkeypatch, tmp_path)

    def timeout(*_args):
        raise subprocess.TimeoutExpired(
            cmd=["fake-e2e"],
            timeout=1,
            output=f"token={GITHUB_TOKEN}\nordinary e2e timeout stdout\n".encode(),
            stderr=f"session_key={SESSION_KEY}\nordinary e2e timeout stderr\n".encode(),
        )

    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", timeout)

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(tmp_path),
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
        == 124
    )
    captured = capsys.readouterr()

    assert GITHUB_TOKEN not in captured.out
    assert SESSION_KEY not in captured.err
    assert "[REDACTED]" in captured.out
    assert "[REDACTED]" in captured.err
    assert "ordinary e2e timeout stdout" in captured.out
    assert "ordinary e2e timeout stderr" in captured.err


def test_sandboxed_web_e2e_timeout_without_captured_streams(monkeypatch, tmp_path, capsys):
    """E2E timeout with no captured streams preserves the empty-output branches."""
    _bind_e2e_services(monkeypatch, tmp_path, log_text="")

    def timeout(*_args):
        raise subprocess.TimeoutExpired(cmd=["fake-e2e"], timeout=1, output=None, stderr=None)

    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", timeout)

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(tmp_path),
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
        == 124
    )
    captured = capsys.readouterr()

    assert "[REDACTED]" not in captured.out
    assert "e2e command timed out after 1s" in captured.err


def test_sandboxed_web_e2e_handles_empty_completed_streams(monkeypatch, tmp_path, capsys):
    """E2E redaction preserves the no-output branch for successful commands."""
    _bind_e2e_services(monkeypatch, tmp_path, log_text="")
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda *_args: subprocess.CompletedProcess(
            args=["fake-e2e"],
            returncode=0,
            stdout="",
            stderr="",
        ),
    )

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(tmp_path),
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()

    assert "[REDACTED]" not in captured.out
    assert captured.err == ""


def test_sandboxed_web_e2e_redacts_explicit_allow_env_value_from_all_evidence(
    monkeypatch, tmp_path, capsys
):
    """An opaque allowed value is removed from E2E streams and backend/frontend log tails."""
    env_name = "CWL_TEST_CREDENTIAL"
    env_value = "opaque-e2e-env-fixture-123456"
    counter = {"value": 0}
    monkeypatch.setattr(sandboxed_verify, "copy_workspace", lambda *_args: tmp_path)
    monkeypatch.setattr(sandboxed_verify, "scrubbed_env", lambda *_args: {env_name: env_value})

    def start_service(label, _command, _cwd, env, logs_dir):
        assert env[env_name] == env_value
        counter["value"] += 1
        log_path = logs_dir / f"{label}-{counter['value']}.log"
        log_path.write_text(f"ordinary service log {env_value}\n", encoding="utf-8")
        return _service(log_path)

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", start_service)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *_args: True)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda _service: None)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda *_args: subprocess.CompletedProcess(
            args=["fake-e2e"],
            returncode=0,
            stdout=f"ordinary e2e stdout {env_value}\n",
            stderr=f"ordinary e2e stderr {env_value}\n",
        ),
    )

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(tmp_path),
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
                "--allow-env",
                env_name,
            ]
        )
        == 0
    )
    captured = capsys.readouterr()

    assert env_value not in captured.out
    assert env_value not in captured.err
    assert "ordinary e2e stdout" in captured.out
    assert "ordinary e2e stderr" in captured.err
    assert captured.out.count("ordinary service log") == 2


def test_sandboxed_web_e2e_redacts_explicit_allow_env_value_on_timeout(
    monkeypatch, tmp_path, capsys
):
    """An opaque explicitly allowed environment value never becomes E2E timeout evidence."""
    env_name = "CWL_TEST_CREDENTIAL"
    env_value = "opaque-e2e-timeout-env-fixture-123456"
    _bind_e2e_services(monkeypatch, tmp_path, log_text="")
    monkeypatch.setattr(sandboxed_verify, "scrubbed_env", lambda *_args: {env_name: env_value})

    def timeout(_command, _cwd, env, timeout_seconds):
        assert env[env_name] == env_value
        raise subprocess.TimeoutExpired(
            cmd=["fake-e2e"],
            timeout=timeout_seconds,
            output=f"ordinary e2e timeout stdout {env_value}\n".encode(),
            stderr=f"ordinary e2e timeout stderr {env_value}\n".encode(),
        )

    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", timeout)

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(tmp_path),
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
                "--e2e-timeout",
                "1",
                "--allow-env",
                env_name,
            ]
        )
        == 124
    )
    captured = capsys.readouterr()

    assert env_value not in captured.out
    assert env_value not in captured.err
    assert "ordinary e2e timeout stdout" in captured.out
    assert "ordinary e2e timeout stderr" in captured.err


def test_wait_for_url_retries_nonready_http_status(monkeypatch, tmp_path):
    """A non-ready HTTP status follows the existing bounded polling path."""

    class RunningProcess:
        def poll(self):
            return None

    class Response:
        status = 503

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    class Opener:
        def open(self, _url, timeout):
            assert timeout == 2
            return Response()

    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(sandboxed_web_e2e.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sandboxed_web_e2e.urllib.request, "build_opener", lambda *_args: Opener())
    service = _service(tmp_path / "unused.log")

    assert sandboxed_web_e2e.wait_for_url("http://127.0.0.1:8000/health", 1, service) is False
