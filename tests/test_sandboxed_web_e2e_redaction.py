"""Regression tests for sandboxed web-E2E log redaction."""

import subprocess

from scripts.ci import sandboxed_web_e2e


def _api_key_fixture() -> str:
    """Return a representative key/value secret fixture."""
    return "api_key: " + "mock_token_string"


def _session_key_fixture() -> str:
    """Return a scanner-safe sensitive assignment fixture."""
    return "session_key=" + "mock_session_value"


def _password_fixture() -> str:
    """Return a scanner-safe password assignment fixture."""
    return "password=" + "mock_password_value"


def test_emit_result_redacts_payload_fields(capsys, tmp_path) -> None:
    """Machine-readable web evidence redacts commands and paths."""
    api_key = _api_key_fixture()
    session_key = _session_key_fixture()
    password = _password_fixture()

    class FakeArgs:
        backend_cmd = f"echo {api_key}"
        frontend_cmd = f"echo {session_key}"
        e2e_cmd = f"echo {password}"
        allow_env: list[str] = []
        evidence_note = "used nothing_sensitive"
        network = "default"
        keep_sandbox = True

    sandboxed_web_e2e.emit_result(
        args=FakeArgs(),
        copied_repo=tmp_path / session_key,
        sandbox_root=tmp_path / "sandbox_test_root",
        backend_ready=True,
        frontend_ready=True,
        exit_code=0,
        elapsed_seconds=1.0,
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "mock_session_value" not in captured.out
    assert "mock_password_value" not in captured.out
    assert "sandbox_test_root" in captured.out


def test_main_redacts_timeout_stdout_and_stderr(monkeypatch, tmp_path, capsys) -> None:
    """The web-E2E timeout handler redacts captured subprocess streams."""
    repo = tmp_path / "repo"
    repo.mkdir()
    api_key = _api_key_fixture()
    password = _password_fixture()

    class FakeProcess:
        def poll(self):
            return None

    def fake_start_service(label, command, _cwd, _env, logs_dir):
        return sandboxed_web_e2e.Service(
            label=label,
            command=command,
            process=FakeProcess(),
            log_path=logs_dir / f"{label}.log",
        )

    def raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=["python", "-c", "pass"],
            timeout=5,
            output=api_key,
            stderr=password,
        )

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start_service)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *_args: True)
    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", raise_timeout)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda _service: None)
    monkeypatch.setattr(sandboxed_web_e2e, "tail_text", lambda _path: "")

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            "python -c pass",
            "--frontend-cmd",
            "python -c pass",
            "--e2e-cmd",
            "python -c pass",
            "--startup-timeout",
            "1",
            "--e2e-timeout",
            "5",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 124
    assert "api_key: [REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "password=[REDACTED]" in captured.err
    assert "mock_password_value" not in captured.err


def test_main_redacts_stdout_stderr_and_log_tail(tmp_path, capsys) -> None:
    """Web-E2E subprocess streams and service log tails are redacted."""
    repo = tmp_path / "repo"
    repo.mkdir()
    api_key = _api_key_fixture()
    session_key = _session_key_fixture()
    password = _password_fixture()

    _ = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            f"python -c \"import sys; print({api_key!r})\"",
            "--frontend-cmd",
            f"python -c \"print({session_key!r})\"",
            "--e2e-cmd",
            (
                "python -c \"import sys; "
                f"print({api_key!r}); "
                f"print({password!r}, file=sys.stderr)\""
            ),
            "--startup-timeout",
            "1",
            "--e2e-timeout",
            "5",
        ]
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "mock_session_value" not in captured.out
    assert "mock_password_value" not in captured.err
