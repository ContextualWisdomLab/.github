"""Regression tests for secret-safe sandbox subprocess evidence."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from scripts.ci import sandboxed_verify, sandboxed_web_e2e
from scripts.ci.redact_sensitive_log import (
    REDACTED,
    redact_command_arguments,
    redact_shell_command,
)


def _provider_token() -> str:
    """Build a credential-shaped fixture without committing a scanner secret."""
    return "gh" + "p_" + ("A" * 36)


def test_redact_command_arguments_covers_separate_equals_and_direct_tokens() -> None:
    """Redact option values, assignments, and provider-shaped standalone values."""
    token = _provider_token()

    assert redact_command_arguments(
        ["tool", "--api-key", token, f"TOKEN={token}", token, "plain"]
    ) == [
        "tool",
        "--api-key",
        REDACTED,
        f"TOKEN={REDACTED}",
        REDACTED,
        "plain",
    ]


def test_redact_shell_command_handles_parsed_and_malformed_input() -> None:
    """Redact parsed commands and fall back to line redaction for bad quoting."""
    token = _provider_token()
    parsed = redact_shell_command(f"tool --password {token} --name safe")
    malformed = redact_shell_command(f"api_key={token}'")

    assert token not in parsed
    assert "--password '[REDACTED]'" in parsed
    assert token not in malformed
    assert REDACTED in malformed


def test_timeout_output_text_redacts_strings_bytes_and_none() -> None:
    """Normalize every TimeoutExpired payload form without leaking credentials."""
    token = _provider_token()

    assert sandboxed_verify.timeout_output_text(None) == ""
    assert sandboxed_verify.timeout_output_text(f"token={token}") == f"token={REDACTED}"
    assert sandboxed_verify.timeout_output_text(f"token={token}".encode()) == f"token={REDACTED}"


def test_sandboxed_verify_redacts_completed_output_command_and_note(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Keep ordinary command completion evidence secret-free end to end."""
    token = _provider_token()
    repository = tmp_path / "repository"
    repository.mkdir()

    def fake_run_command(command, cwd, env, timeout):
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"token={token}\n",
            stderr=f"Authorization: Bearer {token}\n",
        )

    monkeypatch.setattr(sandboxed_verify, "run_command", fake_run_command)

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repository),
            "--evidence-note",
            f"api_key={token}",
            "--",
            "tool",
            "--api-key",
            token,
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert token not in captured.out
    assert token not in captured.err
    assert REDACTED in captured.out
    assert REDACTED in captured.err


class _DoneProcess:
    """Minimal completed-process double accepted by the service cleanup path."""

    pid = 12345

    def poll(self) -> int:
        """Report that the fake service has already exited."""
        return 0

    def wait(self, timeout: int) -> int:
        """Return immediately for interface compatibility."""
        del timeout
        return 0


def test_sandboxed_web_e2e_redacts_commands_output_and_service_logs(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Keep web E2E output, JSON evidence, and service log tails secret-free."""
    token = _provider_token()
    repository = tmp_path / "repository"
    repository.mkdir()

    def fake_start_service(label, command, cwd, env, logs_dir):
        del cwd, env
        log_path = logs_dir / f"{label}.log"
        log_path.write_text(f"secret={token}\n", encoding="utf-8")
        return sandboxed_web_e2e.Service(
            label=label,
            command=command,
            process=cast(subprocess.Popen[str], _DoneProcess()),
            log_path=log_path,
        )

    def fake_run_shell(command, cwd, env, timeout):
        del cwd, env, timeout
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=f"token={token}\n",
            stderr=f"Bearer {token}\n",
        )

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start_service)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda url, timeout, service: True)
    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", fake_run_shell)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repository),
            "--backend-cmd",
            f"backend --token {token}",
            "--frontend-cmd",
            f"frontend TOKEN={token}",
            "--e2e-cmd",
            f"e2e --api-key {token}",
            "--evidence-note",
            f"secret={token}",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert token not in captured.out
    assert token not in captured.err
    assert captured.out.count(REDACTED) >= 7
    assert REDACTED in captured.err


def test_tail_text_handles_missing_and_bounded_existing_logs(tmp_path: Path) -> None:
    """Return nothing for missing logs and redact only the requested final lines."""
    token = _provider_token()
    missing = tmp_path / "missing.log"
    log_path = tmp_path / "service.log"
    log_path.write_text(f"first\nsecond token={token}\nthird\n", encoding="utf-8")

    assert sandboxed_web_e2e.tail_text(missing) == ""
    tail = sandboxed_web_e2e.tail_text(log_path, max_lines=2)
    assert tail == f"second token={REDACTED}\nthird"
    assert token not in tail
