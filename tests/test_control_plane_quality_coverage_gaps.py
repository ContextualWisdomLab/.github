"""Focused branch tests for the central control-plane quality gate."""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.ci import install_base_python_locks as lock_installer
from scripts.ci import redact_sensitive_log as redactor
from scripts.ci import sandboxed_verify
from scripts.ci import sandboxed_web_e2e


DEFERABLE_PIN_OUTPUT = (
    "ERROR: In --require-hashes mode, all requirements must have their "
    "versions pinned with ==. These do not:\n"
)


def completed(returncode: int, stdout: str = "") -> subprocess.CompletedProcess[str]:
    """Return one deterministic subprocess result for a scripted runner."""
    return subprocess.CompletedProcess(
        args=["python", "-m", "pip"],
        returncode=returncode,
        stdout=stdout,
        stderr=None,
    )


def test_lock_installer_deduplicates_a_recovered_group_defensively(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Exercise defensive de-duplication after one grouped supplement recovery."""
    duplicate_file = "requirements-000.txt"
    entries = [
        lock_installer.LockCandidate(
            generated_file=duplicate_file,
            source="module/requirements-a.txt",
            path=tmp_path / "requirements-a.txt",
        ),
        lock_installer.LockCandidate(
            generated_file=duplicate_file,
            source="module/requirements-b.txt",
            path=tmp_path / "requirements-b.txt",
        ),
    ]
    monkeypatch.setattr(lock_installer, "_manifest_entries", lambda _root: entries)
    scripted_results = iter(
        [
            completed(1, DEFERABLE_PIN_OUTPUT),
            completed(1, DEFERABLE_PIN_OUTPUT),
            completed(0),
            completed(0),
        ]
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def runner(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((args, kwargs))
        return next(scripted_results)

    assert lock_installer.install_materialized_locks(tmp_path, runner=runner) == 0
    assert len(calls) == 4


def test_json_string_consumer_covers_escape_and_failure_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover escaped, malformed, non-string, and unterminated JSON strings."""
    escaped = '"quoted \\\"value\\\""'
    parsed = redactor._consume_json_string(escaped, 0, depth=0)
    assert parsed == (escaped, len(escaped))

    assert redactor._consume_json_string('"\\x"', 0, depth=0) is None
    assert redactor._consume_json_string('"unterminated', 0, depth=0) is None

    monkeypatch.setattr(redactor.json, "loads", lambda _candidate: 7)
    assert redactor._consume_json_string('"seven"', 0, depth=0) is None


def test_assignment_consumer_covers_all_scalar_boundaries() -> None:
    """Cover non-identifiers, ordinary keys, empty values, and quoted secrets."""
    assert redactor._consume_sensitive_assignment("=value", 0) == (None, 1)
    assert redactor._consume_sensitive_assignment("ordinary", 0) == (
        None,
        len("ordinary"),
    )
    assert redactor._consume_sensitive_assignment("ordinary=value", 0) == (
        None,
        len("ordinary"),
    )
    assert redactor._consume_sensitive_assignment("api_key=", 0) == (
        None,
        len("api_key"),
    )
    assert redactor._consume_sensitive_assignment("api_key='secret'", 0) == (
        "api_key='[REDACTED]'",
        len("api_key='secret'"),
    )
    assert redactor._consume_sensitive_assignment("api_key='sec\\'ret'", 0) == (
        "api_key='[REDACTED]'",
        len("api_key='sec\\'ret'"),
    )
    unterminated = "api_key='secret"
    assert redactor._consume_sensitive_assignment(unterminated, 0) == (
        "api_key='[REDACTED]",
        len(unterminated),
    )


def test_unstructured_and_argument_helpers_cover_remaining_paths() -> None:
    """Exercise depth, assignment, empty text, argument, and shell fallbacks."""
    assert redactor._redact_unstructured("api_key=secret", depth=9) == (
        "api_key=[REDACTED]"
    )
    assert redactor._redact_unstructured("prefix api_key=secret suffix") == (
        "prefix api_key=[REDACTED] suffix"
    )
    assert redactor.redact_text("") == ""
    assert redactor._redact_json(3) == 3
    assert redactor._redact_assignment("ordinary") == "ordinary"
    assert redactor._redact_assignment("ordinary=value") == "ordinary=value"
    assert redactor._redact_assignment("api_key=value") == "api_key=[REDACTED]"
    assert redactor.redact_command_arguments(
        ["tool", "--token", "secret", "ordinary=value"]
    ) == ["tool", "--token", "[REDACTED]", "ordinary=value"]
    assert redactor.redact_shell_command("'unterminated") == "'unterminated"


def test_sandboxed_verify_standalone_import_path_is_executable() -> None:
    """Load the wrapper without a package so its standalone import fallback runs."""
    namespace = runpy.run_path(sandboxed_verify.__file__, run_name="quality_probe")

    assert callable(namespace["main"])


def test_sandboxed_verify_success_without_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep successful empty stdout and stderr as valid evidence."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    copied_repo = sandbox / "repo"
    copied_repo.mkdir()
    monkeypatch.setattr(
        sandboxed_verify.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(sandbox),
    )
    monkeypatch.setattr(
        sandboxed_verify,
        "copy_workspace",
        lambda *_args, **_kwargs: copied_repo,
    )
    monkeypatch.setattr(
        sandboxed_verify,
        "scrubbed_env",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        sandboxed_verify,
        "run_command",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["true"], returncode=0, stdout="", stderr=""
        ),
    )
    monkeypatch.setattr(sandboxed_verify, "emit_result", lambda **_kwargs: None)
    monkeypatch.setattr(
        sandboxed_verify.shutil,
        "rmtree",
        lambda *_args, **_kwargs: None,
    )

    assert sandboxed_verify.main(["--repo-root", str(tmp_path), "--", "true"]) == 0


def test_wait_for_url_retries_a_transport_error_until_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Return false when readiness transport errors persist through the deadline."""
    process = SimpleNamespace(poll=lambda: None)
    service = SimpleNamespace(process=process, log_path=tmp_path / "service.log")
    opener = SimpleNamespace(
        open=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sandboxed_web_e2e.urllib.error.URLError("offline")
        )
    )
    ticks = iter([0.0, 0.0, 2.0])
    monkeypatch.setattr(
        sandboxed_web_e2e.urllib.request,
        "build_opener",
        lambda *_args: opener,
    )
    monkeypatch.setattr(sandboxed_web_e2e.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(sandboxed_web_e2e.time, "sleep", lambda _seconds: None)

    assert not sandboxed_web_e2e.wait_for_url(
        "https://example.invalid/ready", 1, service
    )


def test_sandboxed_web_e2e_success_without_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Keep successful empty E2E stdout and stderr as valid evidence."""
    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    copied_repo = sandbox / "repo"
    copied_repo.mkdir()
    logs_dir = sandbox / "logs"
    logs_dir.mkdir()
    services = [
        SimpleNamespace(
            label=label,
            command=label,
            process=SimpleNamespace(poll=lambda: None),
            log_path=logs_dir / f"{label}.log",
        )
        for label in ("backend", "frontend")
    ]
    service_iter = iter(services)
    monkeypatch.setattr(
        sandboxed_web_e2e.tempfile,
        "mkdtemp",
        lambda **_kwargs: str(sandbox),
    )
    monkeypatch.setattr(
        sandboxed_web_e2e.sandboxed_verify,
        "copy_workspace",
        lambda *_args, **_kwargs: copied_repo,
    )
    monkeypatch.setattr(
        sandboxed_web_e2e.sandboxed_verify,
        "scrubbed_env",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "start_service",
        lambda *_args, **_kwargs: next(service_iter),
    )
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "wait_for_url",
        lambda *_args, **_kwargs: True,
    )
    monkeypatch.setattr(
        sandboxed_web_e2e,
        "run_shell",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["e2e"], returncode=0, stdout="", stderr=""
        ),
    )
    monkeypatch.setattr(sandboxed_web_e2e, "stop_service", lambda _service: None)
    monkeypatch.setattr(sandboxed_web_e2e, "tail_text", lambda _path: "")
    monkeypatch.setattr(sandboxed_web_e2e, "emit_result", lambda **_kwargs: None)
    monkeypatch.setattr(
        sandboxed_web_e2e.shutil,
        "rmtree",
        lambda *_args, **_kwargs: None,
    )

    assert (
        sandboxed_web_e2e.main(
            [
                "--repo-root",
                str(tmp_path),
                "--backend-cmd",
                "backend",
                "--frontend-cmd",
                "frontend",
                "--e2e-cmd",
                "e2e",
            ]
        )
        == 0
    )
