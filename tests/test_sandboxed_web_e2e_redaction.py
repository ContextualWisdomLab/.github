import pytest
import sys
from scripts.ci import sandboxed_web_e2e
from scripts.ci import sandboxed_verify

def test_emit_result_redacts_payload_fields(capsys, tmp_path):
    class FakeArgs:
        backend_cmd = "echo api_key: 1234567890abcdefghijklmnopqrstuvwxyz"
        frontend_cmd = "echo sk-1234567890abcdefghij"
        e2e_cmd = "echo github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
        allow_env = []
        evidence_note = "used xoxb-1234567890-1234567890"
        network = "default"
        keep_sandbox = True

    sandboxed_web_e2e.emit_result(
        args=FakeArgs(),
        copied_repo=tmp_path / "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890",
        sandbox_root=tmp_path / "xoxb-1234567890-1234567890",
        backend_ready=True,
        frontend_ready=True,
        exit_code=0,
        elapsed_seconds=1.0,
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "1234567890abcdefghijklmnopqrstuvwxyz" not in captured.out
    assert "sk-1234567890abcdefghij" not in captured.out
    assert "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in captured.out
    assert "xoxb-1234567890-1234567890" not in captured.out

def test_main_redacts_stdout_stderr_and_log_tail(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root", str(repo),
            "--backend-cmd", "python -c \"import sys; print('api_key: 1234567890abcdefghijklmnopqrstuvwxyz')\"",
            "--frontend-cmd", "python -c \"print('sk-1234567890abcdefghij')\"",
            "--e2e-cmd", "python -c \"import sys; print('api_key: 1234567890abcdefghijklmnopqrstuvwxyz'); print('github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890', file=sys.stderr)\"",
            "--startup-timeout", "1",
            "--e2e-timeout", "5"
        ]
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "1234567890abcdefghijklmnopqrstuvwxyz" not in captured.out
    assert "sk-1234567890abcdefghij" not in captured.out
    assert "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in captured.err
