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
