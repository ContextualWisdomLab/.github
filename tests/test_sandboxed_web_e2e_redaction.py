from scripts.ci import sandboxed_web_e2e

def test_emit_result_redacts_payload_fields(capsys, tmp_path):
    class FakeArgs:
        backend_cmd = "echo api_key: mock_token_string"
        frontend_cmd = "echo sk-mockkey1234567890abcdefghij"
        e2e_cmd = "echo github" + "_pat_11A2B3C4D5E6F7G8H9I0J_" + "dummy1234567890abcdefghijklmnopqrstuvwxy"
        allow_env = []
        evidence_note = "used nothing_sensitive"
        network = "default"
        keep_sandbox = True

    sandboxed_web_e2e.emit_result(
        args=FakeArgs(),
        copied_repo=tmp_path / ("github" + "_pat_11A2B3C4D5E6F7G8H9I0J_" + "dummy1234567890abcdefghijklmnopqrstuvwxy"),
        sandbox_root=tmp_path / "sandbox_test_root",
        backend_ready=True,
        frontend_ready=True,
        exit_code=0,
        elapsed_seconds=1.0,
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "sk-mockkey1234567890abcdefghij" not in captured.out
    assert "github" + "_pat_11A2B3C4D5E6F7G8H9I0J_" + "dummy1234567890abcdefghijklmnopqrstuvwxy" not in captured.out
    assert "sandbox_test_root" in captured.out

def test_main_redacts_stdout_stderr_and_log_tail(monkeypatch, tmp_path, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()

    _ = sandboxed_web_e2e.main(
        [
            "--repo-root", str(repo),
            "--backend-cmd", "python -c \"import sys; print('api_key: mock_token_string')\"",
            "--frontend-cmd", "python -c \"print('sk-mockkey1234567890abcdefghij')\"",
            "--e2e-cmd", "python -c \"import sys; print('api_key: mock_token_string'); print('github' + '_pat_11A2B3C4D5E6F7G8H9I0J_' + 'dummy1234567890abcdefghijklmnopqrstuvwxy', file=sys.stderr)\"",
            "--startup-timeout", "1",
            "--e2e-timeout", "5"
        ]
    )
    captured = capsys.readouterr()
    assert "[REDACTED]" in captured.out
    assert "mock_token_string" not in captured.out
    assert "sk-mockkey1234567890abcdefghij" not in captured.out
    assert "github" + "_pat_11A2B3C4D5E6F7G8H9I0J_" + "dummy1234567890abcdefghijklmnopqrstuvwxy" not in captured.err
