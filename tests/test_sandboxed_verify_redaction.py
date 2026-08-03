import pytest
from scripts.ci import sandboxed_verify

def test_timeout_output_text_redacts_bytes_and_str():
    assert sandboxed_verify.redact_text(sandboxed_verify.timeout_output_text(b"api_key: 1234567890abcdefghijklmnopqrstuvwxyz")) == "api_key: [REDACTED]"
    assert sandboxed_verify.redact_text(sandboxed_verify.timeout_output_text("github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890")) == "[REDACTED]"

def test_emit_result_redacts_payload_fields(capsys, tmp_path):
    sandboxed_verify.emit_result(
        command=["echo", "api_key: 1234567890abcdefghijklmnopqrstuvwxyz"],
        copied_repo=tmp_path / "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890",
        sandbox_root=tmp_path / "xoxb-1234567890-1234567890",
        exit_code=0,
        elapsed_seconds=1.0,
        kept=True,
        allowed_env=[],
        network="default",
        evidence_note="used api_key: 1234567890abcdefghijklmnopqrstuvwxyz"
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "1234567890abcdefghijklmnopqrstuvwxyz" not in captured.out
    assert "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in captured.out
    assert "xoxb-1234567890-1234567890" not in captured.out

def test_main_redacts_stdout_and_stderr(monkeypatch, tmp_path, capsys):
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
            "import sys; print('api_key: 1234567890abcdefghijklmnopqrstuvwxyz'); print('github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890', file=sys.stderr)"
        ]
    )
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "api_key: [REDACTED]" in captured.out
    assert "1234567890abcdefghijklmnopqrstuvwxyz" not in captured.out
    assert "[REDACTED]" in captured.err
    assert "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in captured.err
