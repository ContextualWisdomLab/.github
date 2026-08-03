"""Regression tests for sandboxed verification output redaction."""

from scripts.ci import sandboxed_verify

API_SECRET = "1234567890" + "abcdefghijklmnopqrstuvwxyz"
GITHUB_PAT = "github_" + "pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
SLACK_TOKEN = "xox" + "b-1234567890-1234567890"


def test_timeout_output_text_redacts_bytes_and_str() -> None:
    """Timeout output is normalized and redacted for bytes and text values."""
    assert (
        sandboxed_verify.redact_text(
            sandboxed_verify.timeout_output_text(
                f"api_key: {API_SECRET}".encode("utf-8")
            )
        )
        == "api_key: [REDACTED]"
    )
    assert (
        sandboxed_verify.redact_text(
            sandboxed_verify.timeout_output_text(GITHUB_PAT)
        )
        == "[REDACTED]"
    )


def test_emit_result_redacts_payload_fields(capsys, tmp_path) -> None:
    """Structured result fields never expose secret-shaped fixture values."""
    sandboxed_verify.emit_result(
        command=["echo", f"api_key: {API_SECRET}"],
        copied_repo=tmp_path / GITHUB_PAT,
        sandbox_root=tmp_path / SLACK_TOKEN,
        exit_code=0,
        elapsed_seconds=1.0,
        kept=True,
        allowed_env=[],
        network="default",
        evidence_note=f"used api_key: {API_SECRET}",
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert API_SECRET not in captured.out
    assert GITHUB_PAT not in captured.out
    assert SLACK_TOKEN not in captured.out


def test_main_redacts_stdout_and_stderr(tmp_path, capsys) -> None:
    """The CLI redacts untrusted subprocess stdout and stderr before emission."""
    repo = tmp_path / "repo"
    repo.mkdir()
    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(repo),
            "--timeout",
            "5",
            "--",
            "python",
            "-c",
            (
                f"import sys; print('api_key: {API_SECRET}'); "
                f"print({GITHUB_PAT!r}, file=sys.stderr)"
            ),
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "api_key: [REDACTED]" in captured.out
    assert API_SECRET not in captured.out
    assert "[REDACTED]" in captured.err
    assert GITHUB_PAT not in captured.err
