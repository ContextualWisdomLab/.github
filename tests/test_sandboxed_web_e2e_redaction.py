from scripts.ci import sandboxed_web_e2e

def test_emit_result_redacts_payload_fields(capsys, tmp_path):
    class FakeArgs:
        backend_cmd = "echo api_key: mock_token_string"
        frontend_cmd = "echo sk-1234567890abcdefghij"
        e2e_cmd = "echo github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890"
        allow_env = []
        evidence_note = "used nothing_sensitive"
        network = "default"
        keep_sandbox = True

    sandboxed_web_e2e.emit_result(
        args=FakeArgs(),
        copied_repo=tmp_path / "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890",
        sandbox_root=tmp_path / "sandbox_test_root",
        backend_ready=True,
        frontend_ready=True,
        exit_code=0,
        elapsed_seconds=1.0,
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "sk-1234567890abcdefghij" not in captured.out
    assert "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in captured.out
    assert "sandbox_test_root" in captured.out

def test_main_redacts_stdout_stderr_and_log_tail(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()

    _ = sandboxed_web_e2e.main(
        [
            "--repo-root", str(repo),
            "--backend-cmd", "python -c \"import sys; print('api_key: mock_token_string')\"",
            "--frontend-cmd", "python -c \"print('sk-1234567890abcdefghij')\"",
            "--e2e-cmd", "python -c \"import sys; print('api_key: mock_token_string'); print('github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890', file=sys.stderr)\"",
            "--startup-timeout", "1",
            "--e2e-timeout", "5"
        ]
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "sk-1234567890abcdefghij" not in captured.out
    assert "github_pat_11A2B3C4D5E6F7G8H9I0J_aBcDeFgHiJkLmNoPqRsTuVwXyZ1234567890" not in captured.err
