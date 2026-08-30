import json
import os
import re
import runpy
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.ci import sandboxed_web_e2e

POSIX_PROCESS_GROUPS = pytest.mark.skipif(os.name == "nt", reason="sandboxed_web_e2e requires POSIX process groups")


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


@POSIX_PROCESS_GROUPS
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
            "--isolation",
            "disabled",
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
    """Small helper branches handle empty URLs, loopback readiness, and hard cleanup."""
    exited = subprocess.Popen([sys.executable, "-c", ""], text=True)
    exited.wait(timeout=5)
    exited_service = sandboxed_web_e2e.Service("done", "true", exited, tmp_path / "missing.log")

    assert sandboxed_web_e2e.wait_for_url("", 1, exited_service) is True
    assert sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service) is False
    assert sandboxed_web_e2e.wait_for_url("http://127.0.0.1:1/", 1, exited_service) is False
    assert sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service) is False
    assert sandboxed_web_e2e.wait_for_url("http://localhost./health", 1, exited_service) is False
    assert sandboxed_web_e2e.wait_for_url("http://127.0.0.2:1/", 1, exited_service) is False
    assert sandboxed_web_e2e.wait_for_url("http://[::1]:1/health", 1, exited_service) is False
    assert sandboxed_web_e2e.wait_for_url("HTTP://[::ffff:127.0.0.1]:1/", 1, exited_service) is False
    assert sandboxed_web_e2e.wait_for_url("https://127.0.0.1:1/", 1, exited_service) is False
    with pytest.raises(ValueError, match="URL must start with http:// or https://"):
        sandboxed_web_e2e.wait_for_url("file:///etc/passwd", 1, exited_service)
    with pytest.raises(ValueError, match=re.escape("URL cannot target external hostname: external.example.com")):
        sandboxed_web_e2e.wait_for_url("http://external.example.com/ready", 1, exited_service)
    with pytest.raises(ValueError, match=re.escape("URL cannot target external hostname: app.localhost")):
        sandboxed_web_e2e.wait_for_url("http://app.localhost:8000/health", 1, exited_service)
    with pytest.raises(ValueError, match=re.escape("URL cannot target external hostname: 169.254.169.254")):
        sandboxed_web_e2e.wait_for_url("http://169.254.169.254/latest/meta-data/", 1, exited_service)
    with pytest.raises(ValueError, match=re.escape("URL cannot target external hostname: 0.0.0.0")):
        sandboxed_web_e2e.wait_for_url("http://0.0.0.0:8000/health", 1, exited_service)
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
    monkeypatch.setattr(sandboxed_web_e2e.os, "killpg", fake_killpg, raising=False)
    monkeypatch.setattr(sandboxed_web_e2e.signal, "SIGKILL", sandboxed_web_e2e.signal.SIGTERM, raising=False)
    sandboxed_web_e2e.stop_service(slow_service)
    assert len(killed) == 2

    killed.clear()
    slow_service = sandboxed_web_e2e.Service("slow", "sleep", SlowProcess(), tmp_path / "slow.log")
    monkeypatch.setattr(sandboxed_web_e2e.os, "killpg", lambda pid, sig: killed.append((pid, sig)), raising=False)
    sandboxed_web_e2e.stop_service(slow_service)
    assert len(killed) == 2


def test_start_service_and_run_shell_capture_bash_contract(monkeypatch, tmp_path):
    """Service startup and shell execution keep logs and bash wiring explicit."""
    popen_calls = []
    run_calls = []

    class FakeProcess:
        pid = 42

        def poll(self):
            return 0

    def fake_popen(*args, **kwargs):
        popen_calls.append((args, kwargs))
        return FakeProcess()

    def fake_run(*args, **kwargs):
        run_calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 7, stdout="out", stderr="err")

    monkeypatch.setattr(sandboxed_web_e2e.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(sandboxed_web_e2e.subprocess, "run", fake_run)

    service = sandboxed_web_e2e.start_service("backend", "npm run dev", tmp_path, {"PATH": "/bin"}, tmp_path)
    completed = sandboxed_web_e2e.run_shell("npm test", tmp_path, {"PATH": "/bin"}, 5)

    assert service.label == "backend"
    assert service.command == "npm run dev"
    assert service.log_path == tmp_path / "backend.log"
    assert popen_calls[0][0] == (["npm", "run", "dev"],)
    assert "shell" not in popen_calls[0][1]
    assert "executable" not in popen_calls[0][1]
    assert popen_calls[0][1]["start_new_session"] is True
    assert completed.returncode == 7
    assert run_calls[0][0] == (["npm", "test"],)
    assert run_calls[0][1]["timeout"] == 5
    assert "shell" not in run_calls[0][1]
    assert "executable" not in run_calls[0][1]


def test_wait_for_url_handles_success_retry_and_log_tail(monkeypatch, tmp_path):
    """Readiness polling accepts HTTP responses after transient URL errors."""

    class RunningProcess:
        def poll(self):
            return None

    class Response:
        def __init__(self, status):
            self.status = status

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    attempts = []

    class FakeOpener:
        def open(self, url, timeout):
            attempts.append((url, timeout))
            if len(attempts) == 1:
                raise sandboxed_web_e2e.urllib.error.URLError("not ready")
            return Response(500 if len(attempts) == 2 else 204)

    monkeypatch.setattr(sandboxed_web_e2e.urllib.request, "build_opener", lambda *args: FakeOpener())
    sleeps = []
    monkeypatch.setattr(sandboxed_web_e2e.time, "sleep", lambda seconds: sleeps.append(seconds))

    log_path = tmp_path / "service.log"
    log_path.write_text("\n".join(f"line-{index}" for index in range(90)), encoding="utf-8")
    service = sandboxed_web_e2e.Service("web", "serve", RunningProcess(), log_path)

    assert sandboxed_web_e2e.wait_for_url("http://127.0.0.1:8000/health", 10, service) is True
    assert len(attempts) == 3
    assert sleeps == [1, 1]
    assert sandboxed_web_e2e.tail_text(log_path).splitlines()[0] == "line-10"


def test_wait_for_url_rejects_non_loopback_and_confused_deputy_targets(tmp_path):
    """Readiness polling must fail closed on public, metadata, and userinfo targets."""
    exited = subprocess.Popen([sys.executable, "-c", ""], text=True)
    exited.wait(timeout=5)
    exited_service = sandboxed_web_e2e.Service("done", "true", exited, tmp_path / "missing.log")

    with pytest.raises(ValueError, match="URL cannot target external hostname: example\\.com"):
        sandboxed_web_e2e.wait_for_url("http://example.com/health", 1, exited_service)
    with pytest.raises(ValueError, match="URL cannot target external hostname: app\\.localhost"):
        sandboxed_web_e2e.wait_for_url("http://app.localhost:8000/health", 1, exited_service)
    with pytest.raises(ValueError, match="URL cannot target external hostname: 169\\.254\\.169\\.254"):
        sandboxed_web_e2e.wait_for_url("http://169.254.169.254/latest/meta-data/", 1, exited_service)
    with pytest.raises(ValueError, match="URL cannot target external hostname: 0\\.0\\.0\\.0"):
        sandboxed_web_e2e.wait_for_url("http://0.0.0.0:8000/health", 1, exited_service)
    with pytest.raises(ValueError, match="URL cannot target external hostname: ::"):
        sandboxed_web_e2e.wait_for_url("http://[::]/", 1, exited_service)
    with pytest.raises(ValueError, match="URL cannot target external hostname: ::ffff:8\\.8\\.8\\.8"):
        sandboxed_web_e2e.wait_for_url("http://[::ffff:8.8.8.8]/", 1, exited_service)
    with pytest.raises(ValueError, match="URL cannot include userinfo"):
        sandboxed_web_e2e.wait_for_url("http://user@127.0.0.1/", 1, exited_service)
    with pytest.raises(ValueError, match="URL cannot include userinfo"):
        sandboxed_web_e2e.wait_for_url("http://:pass@127.0.0.1/", 1, exited_service)
    with pytest.raises(ValueError, match="URL must include a loopback hostname"):
        sandboxed_web_e2e.wait_for_url("http:///health", 1, exited_service)
    sandboxed_web_e2e.stop_service(exited_service)


def test_localhost_resolution_must_stay_loopback(monkeypatch, tmp_path):
    """Literal localhost is allowed only when every resolved address is loopback."""
    exited = subprocess.Popen([sys.executable, "-c", ""], text=True)
    exited.wait(timeout=5)
    exited_service = sandboxed_web_e2e.Service("done", "true", exited, tmp_path / "missing.log")

    monkeypatch.setattr(
        sandboxed_web_e2e.socket,
        "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("8.8.8.8", 0))],
    )
    with pytest.raises(ValueError, match="URL cannot target external hostname: localhost"):
        sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service)

    monkeypatch.setattr(sandboxed_web_e2e.socket, "getaddrinfo", lambda host, port: [])
    with pytest.raises(ValueError, match="URL cannot target unresolved hostname: localhost"):
        sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service)

    def _unresolved(host, port):
        raise socket.gaierror("name not known")

    monkeypatch.setattr(sandboxed_web_e2e.socket, "getaddrinfo", _unresolved)
    with pytest.raises(ValueError, match="URL cannot target unresolved hostname: localhost"):
        sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service)

    monkeypatch.setattr(
        sandboxed_web_e2e.socket,
        "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("not-an-ip", 0))],
    )
    with pytest.raises(ValueError, match="URL cannot target external hostname: localhost"):
        sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service)

    monkeypatch.setattr(
        sandboxed_web_e2e.socket,
        "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("::ffff:8.8.8.8", 0))],
    )
    with pytest.raises(ValueError, match="URL cannot target external hostname: localhost"):
        sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service)

    monkeypatch.setattr(
        sandboxed_web_e2e.socket,
        "getaddrinfo",
        lambda host, port: [(0, 0, 0, "", ("::ffff:127.0.0.1", 0))],
    )
    assert sandboxed_web_e2e.wait_for_url("http://localhost:1/", 1, exited_service) is False
    sandboxed_web_e2e.stop_service(exited_service)


def test_no_redirect_handler_raises_httperror_without_following():
    """Readiness checks must raise HTTPError on redirects to prevent attacker-controlled internal URLs."""
    import urllib.error

    request = sandboxed_web_e2e.urllib.request.Request("https://example.test/ready")

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        sandboxed_web_e2e.NoRedirectHandler().redirect_request(request, None, 302, "Found", {}, "http://127.0.0.1")

    assert exc_info.value.code == 302


def test_wait_for_url_returns_false_after_timeout(monkeypatch, tmp_path):
    """Readiness polling returns false after repeated URL failures."""

    class RunningProcess:
        def poll(self):
            return None

    ticks = iter([0, 0, 2])

    monkeypatch.setattr(sandboxed_web_e2e.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sandboxed_web_e2e.time, "sleep", lambda seconds: None)
    class FailingOpener:
        def open(self, url, timeout):
            raise sandboxed_web_e2e.urllib.error.URLError("still starting")

    monkeypatch.setattr(sandboxed_web_e2e.urllib.request, "build_opener", lambda *args: FailingOpener())

    service = sandboxed_web_e2e.Service("web", "serve", RunningProcess(), tmp_path / "web.log")

    assert sandboxed_web_e2e.wait_for_url("http://127.0.0.1:8000/health", 1, service) is False


def test_main_runs_with_stubbed_services(monkeypatch, tmp_path, capsys):
    """Main records success evidence without requiring real POSIX services."""
    repo = tmp_path / "repo"
    repo.mkdir()
    started = []
    stopped = []

    class DoneProcess:
        def poll(self):
            return 0

    def fake_start(label, command, cwd, env, logs_dir):
        log_path = logs_dir / f"{label}.log"
        log_path.write_text(f"{label} ready\n", encoding="utf-8")
        service = sandboxed_web_e2e.Service(label, command, DoneProcess(), log_path)
        started.append((label, command, cwd, "SANDBOXED_VERIFY" in env))
        return service

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda url, timeout, service: True)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda command, cwd, env, timeout: subprocess.CompletedProcess(
            command,
            0,
            stdout="e2e-out\n",
            stderr="e2e-err\n",
        ),
    )
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: stopped.append(service.label))

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--isolation",
            "disabled",
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--backend-ready-url",
            "http://127.0.0.1:8000/health",
            "--frontend-ready-url",
            "http://127.0.0.1:3000/",
            "--allow-env",
            "GITHUB_TOKEN",
            "--network",
            "required",
            "--evidence-note",
            "needs browser auth",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert [item[0] for item in started] == ["backend", "frontend"]
    assert stopped == ["frontend", "backend"]
    assert "allowed env names=GITHUB_TOKEN" in captured.out
    assert "network=required" in captured.out
    assert "e2e-out" in captured.out
    assert "e2e-err" in captured.err
    assert "--- backend log tail ---" in captured.out
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
    assert payload["backend_ready"] is True
    assert payload["frontend_ready"] is True
    assert payload["exit_code"] == 0
    assert payload["sandbox"] == "(removed)"
    assert payload["network"] == "required"
    assert payload["evidence_note"] == "needs browser auth"


def test_main_runs_required_isolation_with_mapped_environment(monkeypatch, tmp_path, capsys):
    """Required isolation wraps every command and maps sandbox paths into /workspace."""
    repo = tmp_path / "repo"
    repo.mkdir()
    wrapped = []
    started = []

    class DoneProcess:
        def poll(self):
            return 0

    def fake_isolated(command, **kwargs):
        wrapped.append((command, kwargs))
        return f"wrapped {command}"

    def fake_start(label, command, cwd, env, logs_dir):
        log_path = logs_dir / f"{label}.log"
        log_path.write_text(f"{label} ready\n", encoding="utf-8")
        started.append((label, command, cwd, env))
        return sandboxed_web_e2e.Service(label, command, DoneProcess(), log_path)

    monkeypatch.setattr(sandboxed_web_e2e, "isolation_backend", lambda mode: "/usr/bin/bwrap")
    monkeypatch.setattr(sandboxed_web_e2e, "isolated_command", fake_isolated)
    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda url, timeout, service: True)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda command, cwd, env, timeout: subprocess.CompletedProcess(command, 0),
    )
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: None)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert [item[0] for item in wrapped] == ["backend", "frontend", "e2e"]
    assert [item[0] for item in started] == ["backend", "frontend"]
    assert all(item[1].startswith("wrapped ") for item in started)
    assert started[0][3]["HOME"].startswith("/workspace/")
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
    assert payload["isolation"] == "required"
    assert payload["isolation_backend"] == "/usr/bin/bwrap"


def test_main_reports_rejected_isolated_command(monkeypatch, tmp_path, capsys):
    """Rejected commands fail before services start and emit coded evidence."""
    repo = tmp_path / "repo"
    repo.mkdir()
    started = []

    monkeypatch.setattr(sandboxed_web_e2e, "isolation_backend", lambda mode: "/usr/bin/bwrap")
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "isolated_command",
        lambda command, **kwargs: (_ for _ in ()).throw(RuntimeError("host-only tool")),
    )
    monkeypatch.setattr(sandboxed_web_e2e, "start_service", lambda *args: started.append(args))

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 126
    assert not started
    assert "isolation rejected command: host-only tool" in captured.err
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
    assert payload["exit_code"] == 126
    assert payload["isolation_backend"] == "/usr/bin/bwrap"


def test_main_reports_unavailable_required_isolation(monkeypatch, tmp_path, capsys):
    """Required isolation errors exit before starting services with code 126."""
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "isolation_backend",
        lambda mode: (_ for _ in ()).throw(RuntimeError("bwrap unavailable")),
    )

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 126
    assert "bwrap unavailable" in captured.err
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
    assert payload["exit_code"] == 126
    assert payload["isolation_backend"] == "unavailable"


def test_main_reports_stubbed_readiness_failure(monkeypatch, tmp_path, capsys):
    """Main exits distinctly when a stubbed service never becomes ready."""
    repo = tmp_path / "repo"
    repo.mkdir()

    class DoneProcess:
        def poll(self):
            return 0

    def fake_start(label, command, cwd, env, logs_dir):
        log_path = logs_dir / f"{label}.log"
        log_path.write_text(f"{label} not ready\n", encoding="utf-8")
        return sandboxed_web_e2e.Service(label, command, DoneProcess(), log_path)

    def fake_wait(url, timeout, service):
        return service.label == "frontend"

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", fake_wait)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: None)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--isolation",
            "disabled",
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

    assert exit_code == 125
    assert "service readiness failed" in captured.err
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
    assert payload["backend_ready"] is False
    assert payload["frontend_ready"] is True
    assert payload["exit_code"] == 125


def test_main_reports_invalid_readiness_url(monkeypatch, tmp_path, capsys):
    """Invalid readiness input exits with the same clean readiness failure code."""
    repo = tmp_path / "repo"
    repo.mkdir()
    started = []

    class DoneProcess:
        def poll(self):
            return 0

    def fake_start(label, command, cwd, env, logs_dir):
        started.append(label)
        log_path = logs_dir / f"{label}.log"
        log_path.write_text("ready\n", encoding="utf-8")
        return sandboxed_web_e2e.Service(label, command, DoneProcess(), log_path)

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "wait_for_url",
        lambda url, timeout, service: (_ for _ in ()).throw(ValueError("bad host")),
    )
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: None)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--isolation",
            "disabled",
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--backend-ready-url",
            "http://external.example/health",
            "--frontend-ready-url",
            "http://127.0.0.1:3000/",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 125
    assert not started
    assert "invalid readiness URL: URL cannot target external hostname" in captured.err
    result_line = [line for line in captured.out.splitlines() if line.startswith(sandboxed_web_e2e.RESULT_MARKER)][-1]
    payload = json.loads(result_line.removeprefix(sandboxed_web_e2e.RESULT_MARKER).strip())
    assert payload["exit_code"] == 125


def test_main_reports_readiness_exception_after_start(monkeypatch, tmp_path, capsys):
    """Unexpected readiness errors after launch still clean up services."""
    repo = tmp_path / "repo"
    repo.mkdir()
    started = []

    class DoneProcess:
        def poll(self):
            return 0

    def fake_start(label, command, cwd, env, logs_dir):
        started.append(label)
        log_path = logs_dir / f"{label}.log"
        return sandboxed_web_e2e.Service(label, command, DoneProcess(), log_path)

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "wait_for_url",
        lambda url, timeout, service: (_ for _ in ()).throw(ValueError("bad host")),
    )
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: None)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--isolation",
            "disabled",
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

    assert exit_code == 125
    assert started == ["backend", "frontend"]
    assert "invalid readiness URL: bad host" in captured.err


def test_main_reports_stubbed_e2e_timeout(monkeypatch, tmp_path, capsys):
    """Main preserves timeout output from stubbed E2E execution."""
    repo = tmp_path / "repo"
    repo.mkdir()

    class DoneProcess:
        def poll(self):
            return 0

    def fake_start(label, command, cwd, env, logs_dir):
        log_path = logs_dir / f"{label}.log"
        log_path.write_text(f"{label} tail\n", encoding="utf-8")
        return sandboxed_web_e2e.Service(label, command, DoneProcess(), log_path)

    def fake_run_shell(command, cwd, env, timeout):
        raise subprocess.TimeoutExpired(command, timeout, output=b"e2e-out", stderr=b"e2e-err")

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fake_start)
    monkeypatch.setattr(sandboxed_web_e2e, "wait_for_url", lambda url, timeout, service: True)
    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", fake_run_shell)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda service: None)

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--isolation",
            "disabled",
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-timeout",
            "3",
            "--e2e-cmd",
            "e2e",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 124
    assert "e2e-out" in captured.out
    assert "e2e-err" in captured.err
    assert "e2e command timed out after 3s" in captured.err

    def fake_run_shell_with_newlines(command, cwd, env, timeout):
        raise subprocess.TimeoutExpired(command, timeout, output=b"e2e-out\n", stderr=b"e2e-err\n")

    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", fake_run_shell_with_newlines)
    assert sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--isolation",
            "disabled",
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-timeout",
            "3",
            "--e2e-cmd",
            "e2e",
        ]
    ) == 124

    def fake_run_shell_without_output(command, cwd, env, timeout):
        raise subprocess.TimeoutExpired(command, timeout)

    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", fake_run_shell_without_output)
    assert sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(repo),
            "--isolation",
            "disabled",
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-timeout",
            "3",
            "--e2e-cmd",
            "e2e",
        ]
    ) == 124


@POSIX_PROCESS_GROUPS
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
            "--isolation",
            "disabled",
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


@POSIX_PROCESS_GROUPS
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
            "--isolation",
            "disabled",
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


def test_isolation_backend_fails_closed_outside_linux(monkeypatch):
    """Required isolation never silently falls back to a host process."""
    monkeypatch.setattr(sandboxed_web_e2e.platform, "system", lambda: "Darwin")
    with pytest.raises(RuntimeError, match="only supported on Linux"):
        sandboxed_web_e2e.isolation_backend("required")
    assert sandboxed_web_e2e.isolation_backend("disabled") is None


def test_isolation_backend_fails_closed_without_bwrap(monkeypatch):
    """Linux isolation refuses to continue when bubblewrap is not installed."""
    monkeypatch.setattr(sandboxed_web_e2e.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandboxed_web_e2e.shutil, "which", lambda name, path=None: None)
    with pytest.raises(RuntimeError, match="needs bubblewrap"):
        sandboxed_web_e2e.isolation_backend("required")


def test_isolation_backend_returns_bwrap_path_on_linux(monkeypatch):
    """Linux isolation returns the resolved bubblewrap executable."""
    monkeypatch.setattr(sandboxed_web_e2e.platform, "system", lambda: "Linux")
    monkeypatch.setattr(sandboxed_web_e2e.shutil, "which", lambda name, path=None: "/usr/bin/bwrap")
    assert sandboxed_web_e2e.isolation_backend("required") == "/usr/bin/bwrap"


def test_isolated_command_mounts_only_workspace(monkeypatch, tmp_path):
    """Bubblewrap commands expose the copied workspace and not the host root."""
    monkeypatch.setattr(sandboxed_web_e2e.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        sandboxed_web_e2e.shutil,
        "which",
        lambda name, path=None: "/usr/bin/bwrap" if name == "bwrap" else "/usr/bin/python3",
    )
    sandbox = tmp_path / "sandbox"
    repo = sandbox / "repo"
    repo.mkdir(parents=True)
    env = {"PATH": "/usr/bin", "HOME": str(sandbox / "home")}
    command = sandboxed_web_e2e.isolated_command(
        "python3 -c 'print(1)'",
        backend="/usr/bin/bwrap",
        cwd=repo,
        sandbox_root=sandbox,
        env=env,
    )
    assert command.startswith("/usr/bin/bwrap")
    assert "--tmpfs /" in command
    assert "--bind" in command
    assert "--chdir /workspace/repo" in command
    assert "--ro-bind / /" not in command
    assert "--ro-bind /etc/passwd /etc/passwd" in command
    assert "--ro-bind /etc/group /etc/group" in command
    if Path("/etc/nsswitch.conf").exists():
        assert "--ro-bind /etc/nsswitch.conf /etc/nsswitch.conf" in command


def test_isolated_command_rejects_host_home_executable(monkeypatch, tmp_path):
    """Executable paths from a user's home cannot enter the isolated runner."""
    monkeypatch.setattr(
        sandboxed_web_e2e.shutil,
        "which",
        lambda *_args, **_kwargs: str(Path.home() / "bin/tool"),
    )
    sandbox = tmp_path / "sandbox"
    repo = sandbox / "repo"
    repo.mkdir(parents=True)
    with pytest.raises(RuntimeError, match=re.escape("host home directory")):
        sandboxed_web_e2e.isolated_command(
            "tool",
            backend="/usr/bin/bwrap",
            cwd=repo,
            sandbox_root=sandbox,
            env={"PATH": "/usr/bin"},
        )


def test_isolated_command_rejects_executable_outside_bound_roots(monkeypatch, tmp_path):
    """Resolved tools outside read-only mounts fail before entering bubblewrap."""
    monkeypatch.setattr(sandboxed_web_e2e.shutil, "which", lambda *_args, **_kwargs: "/snap/bin/tool")
    sandbox = tmp_path / "sandbox"
    repo = sandbox / "repo"
    repo.mkdir(parents=True)
    with pytest.raises(RuntimeError, match=re.escape("outside the isolated bind roots")):
        sandboxed_web_e2e.isolated_command(
            "tool",
            backend="/usr/bin/bwrap",
            cwd=repo,
            sandbox_root=sandbox,
            env={"PATH": "/usr/bin"},
        )


def test_isolated_command_allows_unresolved_executable_for_bwrap(monkeypatch, tmp_path):
    """Commands with shell-resolved executables still receive the isolated wrapper."""
    monkeypatch.setattr(sandboxed_web_e2e.shutil, "which", lambda *_args, **_kwargs: None)
    sandbox = tmp_path / "sandbox"
    repo = sandbox / "repo"
    repo.mkdir(parents=True)
    command = sandboxed_web_e2e.isolated_command(
        "tool",
        backend="/usr/bin/bwrap",
        cwd=repo,
        sandbox_root=sandbox,
        env={"PATH": "/usr/bin"},
    )
    assert command.startswith("/usr/bin/bwrap")


def test_isolated_command_skips_unavailable_optional_mount(monkeypatch, tmp_path):
    """Optional runtime mounts are omitted when a host path is unavailable."""
    original_exists = Path.exists

    def fake_exists(path):
        if str(path) == "/etc/ssl":
            return False
        return original_exists(path)

    monkeypatch.setattr(Path, "exists", fake_exists)
    monkeypatch.setattr(
        sandboxed_web_e2e.shutil,
        "which",
        lambda name, path=None: "/usr/bin/python3",
    )
    sandbox = tmp_path / "sandbox"
    repo = sandbox / "repo"
    repo.mkdir(parents=True)
    command = sandboxed_web_e2e.isolated_command(
        "python3",
        backend="/usr/bin/bwrap",
        cwd=repo,
        sandbox_root=sandbox,
        env={"PATH": "/usr/bin"},
    )
    assert "--ro-bind /etc/ssl /etc/ssl" not in command


def test_sandbox_environment_maps_host_paths_to_workspace(tmp_path):
    """Only configured sandbox paths are rewritten for the mounted workspace."""
    sandbox = tmp_path / "sandbox"
    env = {
        "HOME": str(sandbox / "home"),
        "TMPDIR": str(sandbox / "tmp"),
        "PATH": "/usr/bin",
    }

    mapped = sandboxed_web_e2e._sandbox_environment(env, sandbox)

    assert mapped is not env
    assert mapped["HOME"] == "/workspace/home"
    assert mapped["TMPDIR"] == "/workspace/tmp"
    assert mapped["PATH"] == "/usr/bin"
    assert "XDG_CACHE_HOME" not in mapped


def test_isolated_command_rejects_empty_command(tmp_path):
    """Empty commands fail before bubblewrap arguments are constructed."""
    with pytest.raises(ValueError, match=re.escape("command must not be empty")):
        sandboxed_web_e2e.isolated_command(
            "   ",
            backend="/usr/bin/bwrap",
            cwd=tmp_path,
            sandbox_root=tmp_path,
            env={"PATH": "/usr/bin"},
        )


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


def test_module_main_entrypoint_parse_error(monkeypatch):
    """The module entrypoint reaches main and propagates argument errors."""
    runpy.run_path(str(Path(sandboxed_web_e2e.__file__)), run_name="not_main")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sandboxed_web_e2e.py",
            "--backend-cmd",
            "backend",
            "--frontend-cmd",
            "frontend",
            "--e2e-cmd",
            "e2e",
            "--startup-timeout",
            "0",
        ],
    )
    module = sys.modules.pop("scripts.ci.sandboxed_web_e2e", None)
    with pytest.raises(SystemExit):
        try:
            runpy.run_module("scripts.ci.sandboxed_web_e2e", run_name="__main__")
        finally:
            if module is not None:
                sys.modules["scripts.ci.sandboxed_web_e2e"] = module


@POSIX_PROCESS_GROUPS
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
            "--isolation",
            "disabled",
            "--backend-cmd",
            f"{sys.executable} -c \"import time; time.sleep(0.2)\"",
            "--frontend-cmd",
            f"{sys.executable} -c \"import time; time.sleep(0.2)\"",
            "--e2e-cmd",
            f"{sys.executable} -c \"raise SystemExit(0)\"",
        ],
    )
    module = sys.modules.pop("scripts.ci.sandboxed_web_e2e", None)
    with pytest.raises(SystemExit) as exc_info:
        try:
            runpy.run_module("scripts.ci.sandboxed_web_e2e", run_name="__main__")
        finally:
            if module is not None:
                sys.modules["scripts.ci.sandboxed_web_e2e"] = module
    assert exc_info.value.code == 0
