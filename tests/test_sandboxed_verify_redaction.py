"""Regression tests for sandboxed verification log redaction."""

from scripts.ci import sandboxed_verify


def _api_key_fixture() -> str:
    """Return a representative key/value secret fixture."""
    return "api_key: " + "mock_token_string"


def _session_key_fixture() -> str:
    """Return a scanner-safe sensitive assignment fixture."""
    return "session_key=" + "mock_session_value"


def test_timeout_output_text_redacts_bytes_and_str() -> None:
    """Timeout output is normalized and redacted for bytes and strings."""
    api_key = _api_key_fixture()
    session_key = _session_key_fixture()

    assert sandboxed_verify.redact_text(
        sandboxed_verify.timeout_output_text(api_key.encode())
    ) == "api_key: [REDACTED]"
    assert sandboxed_verify.redact_text(
        sandboxed_verify.timeout_output_text(session_key)
    ) == "session_key=[REDACTED]"


def test_emit_result_redacts_payload_fields(capsys, tmp_path) -> None:
    """Machine-readable evidence never emits credential-shaped payload values."""
    api_key = _api_key_fixture()
    session_key = _session_key_fixture()
    sandboxed_verify.emit_result(
        command=["echo", api_key],
        copied_repo=tmp_path / session_key,
        sandbox_root=tmp_path / "sandbox_test_root",
        exit_code=0,
        elapsed_seconds=1.0,
        kept=True,
        allowed_env=[],
        network="default",
        evidence_note=f"used {api_key}",
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "mock_session_value" not in captured.out
    assert "sandbox_test_root" in captured.out


def test_main_redacts_stdout_and_stderr(tmp_path, capsys) -> None:
    """Subprocess stdout and stderr are redacted before publication."""
    repo = tmp_path / "repo"
    repo.mkdir()
    api_key = _api_key_fixture()
    session_key = _session_key_fixture()
    command = (
        "import sys; "
        f"print({api_key!r}); "
        f"print({session_key!r}, file=sys.stderr)"
    )

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--timeout",
            "5",
            "--",
            "python",
            "-c",
            command,
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "api_key: [REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "session_key=[REDACTED]" in captured.err
    assert "mock_session_value" not in captured.err
