"""Regression tests for secret-safe sandboxed command output."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.ci import sandboxed_verify, sandboxed_web_e2e


def _fake_personal_access_token() -> str:
    """Build a PAT-shaped fixture without storing a scanner-triggering literal."""

    return "gh" + "p_" + "123456789012345678901234567890123456"


def test_timeout_output_redacts_text_and_bytes() -> None:
    """Timeout normalization must redact secrets in both subprocess payload types."""

    token = _fake_personal_access_token()

    assert sandboxed_verify.timeout_output_text(f"text {token}\n") == "text [REDACTED]\n"
    assert sandboxed_verify.timeout_output_text(f"bytes {token}\n".encode()) == (
        "bytes [REDACTED]\n"
    )


def test_sandboxed_verify_redacts_completed_output(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Ordinary verification stdout and stderr must not disclose captured secrets."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    token = _fake_personal_access_token()

    monkeypatch.setattr(
        sandboxed_verify,
        "run_command",
        lambda command, cwd, env, timeout: subprocess.CompletedProcess(
            command,
            0,
            stdout=f"verify-out {token}\n",
            stderr=f"verify-err {token}\n",
        ),
    )

    assert (
        sandboxed_verify.main(
            ["--repo-root", str(repo_root), "--timeout", "5", "--", "true"]
        )
        == 0
    )
    captured = capsys.readouterr()

    assert token not in captured.out
    assert token not in captured.err
    assert "verify-out [REDACTED]" in captured.out
    assert "verify-err [REDACTED]" in captured.err


def test_sandboxed_web_e2e_redacts_completed_output(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Web E2E command output must be redacted before reaching Actions logs."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    token = _fake_personal_access_token()

    class FinishedProcess:
        """Minimal completed-service process used by the orchestration test."""

        def poll(self) -> int:
            """Report that the synthetic service has already exited cleanly."""

            return 0

    def fake_start_service(label, command, cwd, env, logs_dir):
        """Return a bounded service record without starting a real subprocess."""

        return sandboxed_web_e2e.Service(
            label=label,
            command=command,
            process=FinishedProcess(),
            log_path=logs_dir / f"{label}.log",
        )

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start_service)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "wait_for_url",
        lambda url, timeout, service: True,
    )
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda command, cwd, env, timeout: subprocess.CompletedProcess(
            command,
            0,
            stdout=f"e2e-out {token}\n",
            stderr=f"e2e-err {token}\n",
        ),
    )
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: None)

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(repo_root),
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
                "--startup-timeout",
                "5",
                "--e2e-timeout",
                "5",
            ]
        )
        == 0
    )
    captured = capsys.readouterr()

    assert token not in captured.out
    assert token not in captured.err
    assert "e2e-out [REDACTED]" in captured.out
    assert "e2e-err [REDACTED]" in captured.err
