"""Regression tests for sandboxed web-E2E log redaction."""

from scripts.ci import sandboxed_web_e2e


def _github_pat_fixture() -> str:
    """Return a realistic GitHub token fixture assembled only at runtime."""
    return "github_" + "pat_" + "11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"


def _openai_key_fixture() -> str:
    """Return a representative OpenAI-style test key."""
    return "sk-" + "1234567890abcdefghij"


def _api_key_fixture() -> str:
    """Return a representative key/value secret fixture."""
    return "api_key: " + "mock_token_string"


def test_emit_result_redacts_payload_fields(capsys, tmp_path) -> None:
    """Machine-readable web evidence redacts commands and paths."""
    api_key = _api_key_fixture()
    openai_key = _openai_key_fixture()
    github_pat = _github_pat_fixture()

    class FakeArgs:
        backend_cmd = f"echo {api_key}"
        frontend_cmd = f"echo {openai_key}"
        e2e_cmd = f"echo {github_pat}"
        allow_env: list[str] = []
        evidence_note = "used nothing_sensitive"
        network = "default"
        keep_sandbox = True

    sandboxed_web_e2e.emit_result(
        args=FakeArgs(),
        copied_repo=tmp_path / github_pat,
        sandbox_root=tmp_path / "sandbox_test_root",
        backend_ready=True,
        frontend_ready=True,
        exit_code=0,
        elapsed_seconds=1.0,
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert openai_key not in captured.out
    assert github_pat not in captured.out
    assert "sandbox_test_root" in captured.out


def test_main_redacts_stdout_stderr_and_log_tail(tmp_path, capsys) -> None:
    """Web-E2E subprocess streams and service log tails are redacted."""
    repo = tmp_path / "repo"
    repo.mkdir()
    api_key = _api_key_fixture()
    openai_key = _openai_key_fixture()
    github_pat = _github_pat_fixture()

    _ = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            f"python -c \"import sys; print({api_key!r})\"",
            "--frontend-cmd",
            f"python -c \"print({openai_key!r})\"",
            "--e2e-cmd",
            (
                "python -c \"import sys; "
                f"print({api_key!r}); "
                f"print({github_pat!r}, file=sys.stderr)\""
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
    assert openai_key not in captured.out
    assert github_pat not in captured.err
