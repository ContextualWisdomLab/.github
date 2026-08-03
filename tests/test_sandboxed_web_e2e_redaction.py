"""Regression tests for sandboxed web E2E output redaction."""

from types import SimpleNamespace

from scripts.ci import sandboxed_web_e2e

API_SECRET = "1234567890" + "abcdefghijklmnopqrstuvwxyz"
OPENAI_TOKEN = "sk-" + "1234567890abcdefghij"
GITHUB_PAT = "github_" + "pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
SLACK_TOKEN = "xox" + "b-1234567890-1234567890"


def test_emit_result_redacts_payload_fields(capsys, tmp_path) -> None:
    """Structured E2E result fields redact every secret-shaped fixture value."""
    args = SimpleNamespace(
        backend_cmd=f"echo api_key: {API_SECRET}",
        frontend_cmd=f"echo {OPENAI_TOKEN}",
        e2e_cmd=f"echo {GITHUB_PAT}",
        allow_env=[],
        evidence_note=f"used {SLACK_TOKEN}",
        network="default",
        keep_sandbox=True,
    )

    sandboxed_web_e2e.emit_result(
        args=args,
        copied_repo=tmp_path / GITHUB_PAT,
        sandbox_root=tmp_path / SLACK_TOKEN,
        backend_ready=True,
        frontend_ready=True,
        exit_code=0,
        elapsed_seconds=1.0,
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert API_SECRET not in captured.out
    assert OPENAI_TOKEN not in captured.out
    assert GITHUB_PAT not in captured.out
    assert SLACK_TOKEN not in captured.out


def test_main_redacts_stdout_stderr_and_log_tail(tmp_path, capsys) -> None:
    """The E2E CLI redacts subprocess streams and service log tails."""
    repo = tmp_path / "repo"
    repo.mkdir()

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            f"python -c \"import sys; print('api_key: {API_SECRET}')\"",
            "--frontend-cmd",
            f"python -c \"print('{OPENAI_TOKEN}')\"",
            "--e2e-cmd",
            (
                "python -c \"import sys; "
                f"print('api_key: {API_SECRET}'); "
                f"print('{GITHUB_PAT}', file=sys.stderr)\""
            ),
            "--startup-timeout",
            "1",
            "--e2e-timeout",
            "5",
        ]
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert API_SECRET not in captured.out
    assert OPENAI_TOKEN not in captured.out
    assert GITHUB_PAT not in captured.err
