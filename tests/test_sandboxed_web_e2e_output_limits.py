"""Real-process contracts for bounded sandbox web E2E output."""

from __future__ import annotations

import json
import socket
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from scripts.ci import bounded_subprocess as bounded
from scripts.ci import sandboxed_verify
from scripts.ci import sandboxed_web_e2e


def _command(source: str) -> str:
    """Return one shell-style command that safely launches the current Python."""

    return shlex.join([sys.executable, "-c", source])


def _repository(tmp_path: Path) -> Path:
    """Create one minimal repository accepted by the sandbox copy boundary."""

    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("web E2E fixture\n", encoding="utf-8")
    return repository


def _free_ports(count: int) -> list[int]:
    """Return distinct localhost ports reserved at the same time."""

    listeners = [socket.socket() for _ in range(count)]
    try:
        ports = []
        for listener in listeners:
            listener.bind(("127.0.0.1", 0))
            ports.append(int(listener.getsockname()[1]))
        return ports
    finally:
        for listener in listeners:
            listener.close()


def _http_service_command(port: int, label: str) -> str:
    """Return a bounded-test HTTP service that emits its readiness label."""

    return _command(
        "import http.server\n"
        "import socketserver\n"
        "socketserver.TCPServer.allow_reuse_address=True\n"
        f"server=socketserver.TCPServer(('127.0.0.1',{port}),"
        "http.server.SimpleHTTPRequestHandler)\n"
        f"print({label!r},flush=True)\n"
        "server.serve_forever()\n"
    )


def _result_payload(output: str) -> dict[str, object]:
    """Parse the final machine-readable web E2E result marker."""

    marker = f"{sandboxed_web_e2e.RESULT_MARKER} "
    line = next(
        item for item in reversed(output.splitlines()) if item.startswith(marker)
    )
    return json.loads(line.removeprefix(marker))


def test_start_service_enforces_real_log_file_ceiling(tmp_path: Path) -> None:
    """A long-running child cannot grow its combined service log past the ceiling."""

    logs_directory = tmp_path / "logs"
    logs_directory.mkdir()
    log_limit_bytes = 4096
    service = sandboxed_web_e2e.start_service(
        "backend",
        _command(
            "import os\n"
            "chunk=b'x'*1024\n"
            "while True:\n"
            "    os.write(1,chunk)\n"
        ),
        tmp_path,
        {"PATH": ""},
        logs_directory,
        log_limit_bytes,
    )
    try:
        service.process.wait(timeout=10)
        assert service.log_path.stat().st_size <= log_limit_bytes
        assert sandboxed_web_e2e.service_output_limited(service)
    finally:
        sandboxed_web_e2e.stop_service(service)


def test_service_log_overflow_returns_resource_limit_before_e2e(
    tmp_path: Path,
    capsys,
) -> None:
    """Readiness cannot convert a backend log flood into an ordinary E2E run."""

    sentinel = tmp_path / "e2e-ran"
    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            _command(
                "import os\n"
                "chunk=b'x'*1024\n"
                "while True:\n"
                "    os.write(1,chunk)\n"
            ),
            "--backend-ready-url",
            "http://127.0.0.1:1/ready",
            "--frontend-cmd",
            _command("import time; time.sleep(30)"),
            "--e2e-cmd",
            _command(
                f"from pathlib import Path; Path({str(sentinel)!r}).touch()"
            ),
            "--service-log-limit-bytes",
            "4096",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
    assert "service output exceeded 4096 bytes" in captured.err
    assert payload["output_limited"] is True
    assert payload["output_limit_unsupported"] is False
    assert payload["service_capture_failed"] is False
    assert payload["service_log_limit_bytes"] == 4096
    assert not sentinel.exists()


def test_e2e_output_overflow_is_bounded_and_returns_123(
    tmp_path: Path,
    capsys,
) -> None:
    """The short-lived E2E command uses the same kernel-enforced output boundary."""

    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            _command("import time; time.sleep(30)"),
            "--frontend-cmd",
            _command("import time; time.sleep(30)"),
            "--e2e-cmd",
            _command(
                "import os\n"
                "chunk=b'y'*1024\n"
                "while True:\n"
                "    os.write(2,chunk)\n"
            ),
            "--output-limit-bytes",
            "4096",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
    assert bounded.TRUNCATION_MARKER.strip() in captured.err
    assert "E2E output exceeded 4096 bytes" in captured.err
    assert payload["output_limit_bytes"] == 4096
    assert payload["output_limited"] is True
    assert payload["output_limit_unsupported"] is False
    assert payload["service_capture_failed"] is False
    assert len((captured.out + captured.err).encode("utf-8")) < 25_000


def test_normal_services_and_e2e_preserve_existing_success_contract(
    tmp_path: Path,
    capsys,
) -> None:
    """Ordinary services, Unicode output, cleanup, and evidence remain unchanged."""

    backend_port, frontend_port = _free_ports(2)
    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            _http_service_command(backend_port, "backend-ready"),
            "--frontend-cmd",
            _http_service_command(frontend_port, "frontend-ready"),
            "--backend-ready-url",
            f"http://127.0.0.1:{backend_port}/README.md",
            "--frontend-ready-url",
            f"http://127.0.0.1:{frontend_port}/README.md",
            "--e2e-cmd",
            _command("print('통합 성공')"),
            "--output-limit-bytes",
            "4096",
            "--service-log-limit-bytes",
            "4096",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == 0
    assert "통합 성공" in captured.out
    assert "backend-ready" in captured.out
    assert "frontend-ready" in captured.out
    assert payload["output_limited"] is False
    assert payload["output_limit_unsupported"] is False
    assert payload["service_capture_failed"] is False
    assert payload["output_limit_bytes"] == 4096
    assert payload["service_log_limit_bytes"] == 4096


def test_tail_text_uses_bounded_suffix_and_tolerates_partial_utf8(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """Service evidence delegates to a byte-bounded suffix before line selection."""

    log_path = tmp_path / "service.log"
    log_path.write_bytes(b"ignored" + "가".encode("utf-8"))
    observed: dict[str, object] = {}

    def fake_suffix(path: Path, maximum_bytes: int) -> bounded.BoundedText:
        observed["path"] = path
        observed["maximum_bytes"] = maximum_bytes
        return bounded.BoundedText(
            text=f"{bounded.TRUNCATION_MARKER}�\nlast-line\n",
            truncated=True,
            stored_bytes=10_000,
        )

    monkeypatch.setattr(bounded, "read_bounded_suffix", fake_suffix)

    tail = sandboxed_web_e2e.tail_text(
        log_path,
        max_lines=2,
        max_bytes=4096,
    )

    assert observed == {"path": log_path, "maximum_bytes": 4096}
    assert tail == f"{bounded.TRUNCATION_MARKER.strip()}\n�\nlast-line"


def test_unsupported_resource_boundary_fails_closed(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """Service startup cannot silently continue without file-size enforcement."""

    def fail_start(*args, **kwargs):
        del args, kwargs
        raise bounded.OutputLimitUnsupportedError("unsupported")

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", fail_start)
    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            _command("pass"),
            "--frontend-cmd",
            _command("pass"),
            "--e2e-cmd",
            _command("pass"),
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
    assert "bounded child output is unavailable" in captured.err
    assert payload["output_limited"] is False
    assert payload["output_limit_unsupported"] is True
    assert payload["service_capture_failed"] is False


@pytest.mark.parametrize("missing_role", ["backend", "frontend", "e2e"])
def test_missing_executable_returns_stable_failed_evidence(
    tmp_path: Path,
    capsys,
    missing_role: str,
) -> None:
    """Every command role reports a missing executable without a traceback."""

    commands = {
        "backend": _command("import time; time.sleep(30)"),
        "frontend": _command("import time; time.sleep(30)"),
        "e2e": _command("print('ready')"),
    }
    commands[missing_role] = "missing-web-e2e-executable"
    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            commands["backend"],
            "--frontend-cmd",
            commands["frontend"],
            "--e2e-cmd",
            commands["e2e"],
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == sandboxed_verify.COMMAND_NOT_FOUND_EXIT_CODE
    assert payload["exit_code"] == sandboxed_verify.COMMAND_NOT_FOUND_EXIT_CODE
    assert "install each executable or correct command PATH" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("--output-limit-bytes", "4095"),
        (
            "--service-log-limit-bytes",
            str(bounded.MAXIMUM_OUTPUT_LIMIT_BYTES + 1),
        ),
    ],
)
def test_cli_rejects_unsafe_command_and_service_budgets(
    tmp_path: Path,
    option: str,
    value: str,
) -> None:
    """Both output budgets fail parsing outside the explicit safe range."""

    repository = _repository(tmp_path)
    base = [
        "--repo-root",
        str(repository),
        "--backend-cmd",
        _command("pass"),
        "--frontend-cmd",
        _command("pass"),
        "--e2e-cmd",
        _command("pass"),
    ]
    with pytest.raises(SystemExit) as raised:
        sandboxed_web_e2e.parse_args([*base, option, value])
    assert raised.value.code == 2


def test_kept_sandbox_service_file_never_exceeds_kernel_ceiling(
    tmp_path: Path,
    capsys,
) -> None:
    """Persisted debugging sandboxes retain only the bounded service artifact."""

    log_limit_bytes = 4096
    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            _command(
                "import os\n"
                "chunk=b'z'*1024\n"
                "while True:\n"
                "    os.write(1,chunk)\n"
            ),
            "--frontend-cmd",
            _command("import time; time.sleep(30)"),
            "--e2e-cmd",
            _command("pass"),
            "--service-log-limit-bytes",
            str(log_limit_bytes),
            "--keep-sandbox",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)
    sandbox_path = Path(str(payload["sandbox"]))

    try:
        assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
        assert (
            sandbox_path / "logs" / "backend.log"
        ).stat().st_size <= log_limit_bytes
    finally:
        shutil.rmtree(sandbox_path, ignore_errors=True)
