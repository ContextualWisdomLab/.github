"""Coverage closure for defensive central control-plane execution branches."""

from __future__ import annotations

import io
import runpy
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts.ci import install_base_python_locks as installer
from scripts.ci import redact_sensitive_log as redactor
from scripts.ci import sandboxed_verify, sandboxed_web_e2e


def test_json_string_scanner_handles_escapes_and_fail_closed_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise escaped, malformed, non-string, and unterminated JSON strings."""

    escaped = r'"a\"b"'
    assert redactor._consume_json_string(escaped, 0, depth=0) == (
        escaped,
        len(escaped),
    )
    assert redactor._consume_json_string(r'"\q"', 0, depth=0) is None
    assert redactor._consume_json_string('"unterminated', 0, depth=0) is None

    monkeypatch.setattr(redactor.json, "loads", lambda _candidate: 7)
    assert redactor._consume_json_string('"ordinary"', 0, depth=0) is None


def test_assignment_scanner_handles_missing_escaped_and_unterminated_values() -> None:
    """Defensive assignment parsing covers every quoted-value termination path."""

    missing, _cursor = redactor._consume_sensitive_assignment("password =   ", 0)
    assert missing is None

    escaped_text = r'password="a\"b" --safe'
    escaped_replacement, escaped_end = redactor._consume_sensitive_assignment(
        escaped_text,
        0,
    )
    assert escaped_replacement == 'password="[REDACTED]"'
    assert escaped_text[escaped_end:] == " --safe"

    unterminated_text = "password='plain secret"
    unterminated_replacement, unterminated_end = (
        redactor._consume_sensitive_assignment(unterminated_text, 0)
    )
    assert unterminated_replacement == "password='[REDACTED]"
    assert unterminated_end == len(unterminated_text)


def test_unstructured_and_structured_redaction_defensive_fallbacks() -> None:
    """Depth, malformed-string, scalar-JSON, and unusual string edges stay safe."""

    assert redactor._redact_unstructured("token=plain-secret", depth=9) == (
        "token=[REDACTED]"
    )
    assert redactor._redact_unstructured(r'"\q"') == r'"\q"'
    assert redactor._redact_json(17) == 17

    class NonEmptyStringWithoutLines(str):
        """Represent a valid string subtype with an adversarial splitlines result."""

        def splitlines(self, keepends: bool = False) -> list[str]:
            """Return no lines while retaining a non-empty scalar value."""

            del keepends
            return []

    unusual = NonEmptyStringWithoutLines("api_key=plain-secret")
    assert redactor.redact_text(unusual) == "api_key=[REDACTED]"


def test_installer_skips_deferable_candidate_without_empty_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty bounded resolver diagnostic does not emit a meaningless line."""

    lock_path = tmp_path / "requirements-000.txt"
    lock_path.write_text("demo==1 --hash=sha256:" + ("a" * 64) + "\n")
    entry = installer.LockCandidate(
        generated_file="requirements-000.txt",
        source="requirements-agent.txt",
        path=lock_path,
    )
    monkeypatch.setattr(installer, "_manifest_entries", lambda _root: [entry])
    monkeypatch.setattr(
        installer,
        "_is_deferable_preflight_failure",
        lambda _output: True,
    )
    monkeypatch.setattr(installer, "_bounded_failure_output", lambda _output: "")

    def runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, stdout="")

    stdout = io.StringIO()
    stderr = io.StringIO()
    assert (
        installer.install_materialized_locks(
            tmp_path,
            runner=runner,
            stdout=stdout,
            stderr=stderr,
        )
        == 0
    )
    assert "Skipping trusted base Python requirement candidate" in stderr.getvalue()
    assert stderr.getvalue().endswith("group completed it.\n")


def test_installer_deduplicates_recovered_same_file_plan(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A defensive duplicate recovered entry is installed only once."""

    lock_path = tmp_path / "requirements-000.txt"
    lock_path.write_text("demo==1 --hash=sha256:" + ("b" * 64) + "\n")
    entries = [
        installer.LockCandidate(
            generated_file="requirements-000.txt",
            source="backend/requirements-agent.txt",
            path=lock_path,
        ),
        installer.LockCandidate(
            generated_file="requirements-000.txt",
            source="backend/requirements-hashes.txt",
            path=lock_path,
        ),
    ]
    monkeypatch.setattr(installer, "_manifest_entries", lambda _root: entries)
    commands: list[list[str]] = []
    deferable = (
        "ERROR: In --require-hashes mode, all requirements must have their "
        "versions pinned with ==: demo>=1"
    )

    def runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        if "--dry-run" in command and len(commands) <= 2:
            return subprocess.CompletedProcess(command, 1, stdout=deferable)
        return subprocess.CompletedProcess(command, 0, stdout="")

    stdout = io.StringIO()
    assert (
        installer.install_materialized_locks(
            tmp_path,
            runner=runner,
            stdout=stdout,
            stderr=io.StringIO(),
        )
        == 0
    )
    assert len(commands) == 4
    assert commands[-1].count("-r") == 1
    assert "installed=1 skipped=0" in stdout.getvalue()


def test_sandboxed_verify_script_path_bootstraps_import_root() -> None:
    """Direct script-path loading executes the package bootstrap branch."""

    original_path = list(sys.path)
    try:
        namespace = runpy.run_path(
            str(Path(sandboxed_verify.__file__).resolve()),
            run_name="sandboxed_verify_import_probe",
        )
    finally:
        sys.path[:] = original_path
    assert namespace["RESULT_MARKER"] == sandboxed_verify.RESULT_MARKER


@pytest.mark.parametrize(
    ("stdout_payload", "stderr_payload"),
    [("only-stdout", None), (None, "only-stderr")],
)
def test_sandboxed_verify_timeout_accepts_one_missing_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stdout_payload: str | None,
    stderr_payload: str | None,
) -> None:
    """A timeout publishes either available stream without assuming both exist."""

    repository = tmp_path / "repository"
    repository.mkdir()

    def timeout_runner(
        command: list[str],
        _cwd: Path,
        _env: dict[str, str],
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout_payload,
            stderr=stderr_payload,
        )

    monkeypatch.setattr(sandboxed_verify, "run_command", timeout_runner)
    assert (
        sandboxed_verify.main(
            ["--repo-root", str(repository), "--timeout", "1", "--", "true"]
        )
        == 124
    )
    captured = capsys.readouterr()
    if stdout_payload is None:
        assert "only-stdout" not in captured.out
    else:
        assert stdout_payload in captured.out
    if stderr_payload is None:
        assert "only-stderr" not in captured.err
    else:
        assert stderr_payload in captured.err


def test_wait_for_url_retries_non_acceptable_http_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A 5xx response remains unready and polling proceeds to the deadline."""

    class RunningProcess:
        """Minimal still-running process double."""

        def poll(self) -> None:
            """Report that the service remains active."""

            return None

    class Response:
        """Context-managed unacceptable HTTP response."""

        status = 503

        def __enter__(self) -> "Response":
            """Return the response object."""

            return self

        def __exit__(self, *_args: object) -> bool:
            """Do not suppress exceptions."""

            return False

    class Opener:
        """Return one deterministic response."""

        def open(self, _url: str, timeout: int) -> Response:
            """Return the 503 response with the expected bounded timeout."""

            assert timeout == 2
            return Response()

    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(sandboxed_web_e2e.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(
        sandboxed_web_e2e.urllib.request,
        "build_opener",
        lambda *_handlers: Opener(),
    )
    service = sandboxed_web_e2e.Service(
        "web",
        "serve",
        RunningProcess(),  # type: ignore[arg-type]
        tmp_path / "web.log",
    )
    assert (
        sandboxed_web_e2e.wait_for_url(
            "http://127.0.0.1:8000/health",
            1,
            service,
        )
        is False
    )


@pytest.mark.parametrize(
    ("stdout_payload", "stderr_payload"),
    [("only-stdout", None), (None, "only-stderr")],
)
def test_sandboxed_web_timeout_accepts_one_missing_stream(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    stdout_payload: str | None,
    stderr_payload: str | None,
) -> None:
    """Web E2E timeout reporting handles absent stdout or stderr independently."""

    repository = tmp_path / "repository"
    repository.mkdir()

    class DoneProcess:
        """Minimal completed service process double."""

        def poll(self) -> int:
            """Report successful completion."""

            return 0

    def start_service(
        label: str,
        command: str,
        _cwd: Path,
        _env: dict[str, str],
        logs_dir: Path,
    ) -> sandboxed_web_e2e.Service:
        log_path = logs_dir / f"{label}.log"
        log_path.write_text("", encoding="utf-8")
        return sandboxed_web_e2e.Service(
            label,
            command,
            DoneProcess(),  # type: ignore[arg-type]
            log_path,
        )

    def timeout_runner(
        command: str,
        _cwd: Path,
        _env: dict[str, str],
        timeout: int,
    ) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(
            command,
            timeout,
            output=stdout_payload,
            stderr=stderr_payload,
        )

    monkeypatch.setattr(sandboxed_web_e2e, "start_service", start_service)
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "wait_for_url",
        lambda _url, _timeout, _service: True,
    )
    monkeypatch.setattr(sandboxed_web_e2e, "run_shell", timeout_runner)
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda _service: None)

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(repository),
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-timeout",
                "1",
                "--e2e-cmd",
                "e2e",
            ]
        )
        == 124
    )
    captured = capsys.readouterr()
    if stdout_payload is None:
        assert "only-stdout" not in captured.out
    else:
        assert stdout_payload in captured.out
    if stderr_payload is None:
        assert "only-stderr" not in captured.err
    else:
        assert stderr_payload in captured.err
