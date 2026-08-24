import subprocess

from scripts.ci import bounded_subprocess, sandboxed_web_e2e


def test_web_e2e_reports_bounded_capture_finalization_failure(
    monkeypatch,
    tmp_path,
    capsys,
):
    """A service-capture finalization failure remains a bounded hard failure."""

    repo = tmp_path / "repo"
    repo.mkdir()

    class DoneProcess:
        pid = 12345

        def poll(self):
            return 0

    def fake_start(
        label,
        command,
        cwd,
        env,
        logs_dir,
        log_limit_bytes=bounded_subprocess.DEFAULT_SERVICE_LOG_LIMIT_BYTES,
    ):
        del cwd, env
        log_path = logs_dir / f"{label}.log"
        log_path.write_text(f"{label} ready\n", encoding="utf-8")
        return sandboxed_web_e2e.Service(
            label=label,
            command=command,
            process=DoneProcess(),
            log_path=log_path,
            log_limit_bytes=log_limit_bytes,
        )

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda *args: True)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["e2e"],
            returncode=0,
            stdout="ok\n",
            stderr="",
        ),
    )

    def fail_capture_finalization(service):
        raise OSError(f"cannot finalize {service.label}")

    monkeypatch.setattr(
        sandboxed_web_e2e,
        "stop_service",
        fail_capture_finalization,
    )
    monkeypatch.setattr(
        bounded_subprocess,
        "kill_process_group",
        lambda _process: None,
    )

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--backend-ready-url",
            "http://127.0.0.1:8000/health",
            "--frontend-ready-url",
            "http://127.0.0.1:3000/",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE
    assert captured.err.count("bounded service capture failed") == 2
    assert f'"exit_code": {bounded_subprocess.OUTPUT_LIMIT_EXIT_CODE}' in captured.out
    assert '"output_limited": false' in captured.out
    assert '"output_limit_unsupported": false' in captured.out
    assert '"service_capture_failed": true' in captured.out
