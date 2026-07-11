import json
import os
import runpy
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import sandboxed_web_e2e

pytestmark = pytest.mark.skipif(os.name == "nt", reason="sandboxed_web_e2e requires POSIX process groups")


def free_port():
    """Return an available localhost TCP port for a short-lived test service."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def http_server_command(port: int, label: str) -> str:
    """Build a simple Python HTTP service command."""
    return (
        f"{sys.executable} -c \""
        "import http.server, socketserver; "
        "socketserver.TCPServer.allow_reuse_address=True; "
        f"handler=http.server.SimpleHTTPRequestHandler; "
        f"server=socketserver.TCPServer(('127.0.0.1', {port}), handler); "
        f"print('{label} ready', flush=True); "
        "server.serve_forever()"
        "\""
    )


def test_sandboxed_web_e2e_runs_services_and_does_not_mutate_source(tmp_path, capsys):
    """Web E2E helper runs backend/frontend plus E2E in a copied workspace."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "index.html").write_text("ok", encoding="utf-8")
    backend_port = free_port()
    frontend_port = free_port()
    e2e_cmd = (
        f"{sys.executable} -c \""
        "import pathlib, sys, urllib.request; "
        f"print(urllib.request.urlopen('http://127.0.0.1:{backend_port}/index.html').status); "
        f"print(urllib.request.urlopen('http://127.0.0.1:{frontend_port}/index.html').status); "
        "print('e2e-stderr', file=sys.stderr); "
        "pathlib.Path('e2e-created.txt').write_text('sandbox-only')"
        "\""
    )

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            http_server_command(backend_port, "backend"),
            "--frontend-cmd",
            http_server_command(frontend_port, "frontend"),
            "--backend-ready-url",
            f"http://127.0.0.1:{backend_port}/index.html",
            "--frontend-ready-url",
            f"http://127.0.0.1:{frontend_port}/index.html",
            "--startup-timeout",
            "20",
            "--e2e-timeout",
            "20",
            "--allow-env",
            "GITHUB_TOKEN",
            "--network",
            "not-required",
            "--evidence-note",
            "local web app e2e",
            "--e2e-cmd",
            e2e_cmd,
        ]
    )
    captured = capsys.readouterr()

    if exit_code == 125:
        result_lines = [
            line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)
        ]
        if result_lines:
            payload = json.loads(result_lines[-1].removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
            if payload["backend_ready"] is False or payload["frontend_ready"] is False:
                pytest.skip("runner could not start localhost services for sandboxed web E2E")

    assert exit_code == 0
    assert "SANDBOXED_WEB_E2E_RESULT" in captured.out
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
    assert payload["backend_ready"] is True
    assert payload["frontend_ready"] is True
    assert payload["exit_code"] == 0
    assert payload["sandboxed"] is True
    assert payload["allowed_env"] == ["GITHUB_TOKEN"]
    assert payload["network"] == "not-required"
    assert payload["evidence_note"] == "local web app e2e"
    assert "e2e-stderr" in captured.err
    assert not (repo / "e2e-created.txt").exists()


def test_wait_helpers_and_service_cleanup_edges(monkeypatch, tmp_path):
    """Small helper branches handle empty URLs, exited services, and hard cleanup."""
    exited = subprocess.Popen([sys.executable, "-c", ""], text=True)
    exited.wait(timeout=5)
    exited_service = sandboxed_web_e2e.Service("done", "true", exited, tmp_path / "missing.log")

    assert sandboxed_web_e2e.wait_for_url("", 1, exited_service) is True
    assert sandboxed_web_e2e.wait_for_url("http://127.0.0.1:1/", 1, exited_service) is False
    with pytest.raises(ValueError, match="URL must start with http:// or https://"):
        sandboxed_web_e2e.wait_for_url("file:///etc/passwd", 1, exited_service)
    sandboxed_web_e2e.stop_service(exited_service)
    assert sandboxed_web_e2e.tail_text(tmp_path / "missing.log") == ""

    class SlowProcess:
        pid = 12345

        def __init__(self):
            self.waits = 0

        def poll(self):
            return None

        def wait(self, timeout):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired("slow", timeout)
            return 0

    killed = []

    def fake_killpg(pid, sig):
        killed.append((pid, sig))
        if len(killed) == 2:
            raise ProcessLookupError

    slow_service = sandboxed_web_e2e.Service("slow", "sleep", SlowProcess(), tmp_path / "slow.log")
    monkeypatch.setattr(sandboxed_web_e2e.os, "killpg", fake_killpg)
    sandboxed_web_e2e.stop_service(slow_service)
    assert len(killed) == 2

    killed.clear()
    slow_service = sandboxed_web_e2e.Service("slow", "sleep", SlowProcess(), tmp_path / "slow.log")
    monkeypatch.setattr(sandboxed_web_e2e.os, "killpg", lambda pid, sig: killed.append((pid, sig)))
    sandboxed_web_e2e.stop_service(slow_service)
    assert len(killed) == 2


def test_sandboxed_web_e2e_reports_readiness_failure(tmp_path, capsys):
    """Readiness failures return a distinct nonzero exit code."""
    repo = tmp_path / "repo"
    repo.mkdir()
    backend_port = free_port()
    frontend_port = free_port()

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            http_server_command(backend_port, "backend"),
            "--frontend-cmd",
            http_server_command(frontend_port, "frontend"),
            "--backend-ready-url",
            "http://127.0.0.1:1/not-ready",
            "--frontend-ready-url",
            f"http://127.0.0.1:{frontend_port}/",
            "--startup-timeout",
            "1",
            "--e2e-timeout",
            "5",
            "--e2e-cmd",
            f"{sys.executable} -c \"raise SystemExit(99)\"",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 125
    assert "service readiness failed" in captured.err
    assert "SANDBOXED_WEB_E2E_RESULT" in captured.out


def test_sandboxed_web_e2e_reports_e2e_timeout(monkeypatch, tmp_path, capsys):
    """E2E command timeout is reported without losing captured output."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def fake_run_shell(command, cwd, env, timeout):
        raise subprocess.TimeoutExpired(command, timeout, output="e2e-out", stderr="e2e-err")

    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", fake_run_shell)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            f"{sys.executable} -c \"import time; time.sleep(3)\"",
            "--frontend-cmd",
            f"{sys.executable} -c \"import time; time.sleep(3)\"",
            "--e2e-cmd",
            "fake e2e",
            "--e2e-timeout",
            "1",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 124
    assert "e2e-out" in captured.out
    assert "e2e-err" in captured.err
    assert "e2e command timed out after 1s" in captured.err
    assert "SANDBOXED_WEB_E2E_RESULT" in captured.out


def test_parse_args_rejects_invalid_inputs():
    """The CLI rejects unusable timeout and environment values."""
    with pytest.raises(SystemExit):
        sandboxed_web_e2e.parse_args(
            [
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
                "--startup-timeout",
                "0",
            ]
        )
    with pytest.raises(SystemExit):
        sandboxed_web_e2e.parse_args(
            [
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
                "--e2e-timeout",
                "0",
            ]
        )
    with pytest.raises(SystemExit):
        sandboxed_web_e2e.parse_args(
            [
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
                "--allow-env",
                "bad-name!",
            ]
        )


def test_module_import_and_main_entrypoint(monkeypatch, tmp_path):
    """The script can run through its module entrypoint."""
    script_path = Path(sandboxed_web_e2e.__file__)
    runpy.run_path(str(script_path), run_name="not_main")

    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sandboxed_web_e2e.py",
            "--repo-root",
            str(repo),
            "--backend-cmd",
            f"{sys.executable} -c \"import time; time.sleep(0.2)\"",
            "--frontend-cmd",
            f"{sys.executable} -c \"import time; time.sleep(0.2)\"",
            "--e2e-cmd",
            f"{sys.executable} -c \"raise SystemExit(0)\"",
        ],
    )
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("scripts.ci.sandboxed_web_e2e", run_name="__main__")
    assert exc_info.value.code == 0
