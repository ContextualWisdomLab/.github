"""Real-command contracts for sandboxed verification output ceilings."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

from scripts.ci import bounded_subprocess as bounded
from scripts.ci import sandboxed_verify


def _result_payload(output: str) -> dict[str, object]:
    """Parse the final sandbox result marker from captured standard output."""

    marker = f"{sandboxed_verify.RESULT_MARKER} "
    result_line = next(
        line for line in reversed(output.splitlines()) if line.startswith(marker)
    )
    return json.loads(result_line.removeprefix(marker))


def _repository(tmp_path: Path) -> Path:
    """Create one minimal repository directory accepted by the copy boundary."""

    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "README.md").write_text("sandbox fixture\n", encoding="utf-8")
    return repository


def test_normal_command_preserves_output_and_reports_declared_limit(
    tmp_path: Path,
    capsys,
) -> None:
    """Ordinary Unicode output remains visible with deterministic limit evidence."""

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--output-limit-bytes",
            "4096",
            "--",
            sys.executable,
            "-c",
            "import sys; print('정상'); print('경고', file=sys.stderr)",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == 0
    assert "정상" in captured.out
    assert "경고" in captured.err
    assert payload["output_limit_bytes"] == 4096
    assert payload["output_limited"] is False


@pytest.mark.parametrize("descriptor", [1, 2])
def test_excessive_stdout_or_stderr_returns_resource_limit_code(
    tmp_path: Path,
    capsys,
    descriptor: int,
) -> None:
    """A real output flood is bounded and classified as exit 123."""

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--output-limit-bytes",
            "4096",
            "--",
            sys.executable,
            "-c",
            (
                "import os\n"
                f"descriptor={descriptor}\n"
                "chunk=b'x'*1024\n"
                "while True:\n"
                "    os.write(descriptor, chunk)\n"
            ),
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)
    combined = captured.out + captured.err

    assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
    assert bounded.TRUNCATION_MARKER.strip() in combined
    assert "output exceeded 4096 bytes" in captured.err
    assert payload["output_limited"] is True
    assert len(combined.encode("utf-8")) < 20_000


def test_timeout_retains_precedence_and_bounded_partial_output(
    tmp_path: Path,
    capsys,
) -> None:
    """A timeout remains exit 124 while its partial output stays byte-bounded."""

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--timeout",
            "1",
            "--output-limit-bytes",
            "4096",
            "--",
            sys.executable,
            "-c",
            "import os,time; os.write(1,b'before\\n'); time.sleep(30)",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == 124
    assert "before" in captured.out
    assert "timed out after 1s" in captured.err
    assert payload["output_limited"] is False


@pytest.mark.parametrize(
    "capture_error",
    [RuntimeError("host descriptor detail"), OSError("reader failed")],
)
def test_stuck_capture_returns_bounded_failure_without_traceback(
    monkeypatch,
    tmp_path: Path,
    capsys,
    capture_error: BaseException,
) -> None:
    """A stuck reader becomes stable resource evidence instead of a traceback."""
    repository = _repository(tmp_path)
    monkeypatch.setattr(
        sandboxed_verify,
        "run_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(capture_error),
    )

    exit_code = sandboxed_verify.main(
        ["--repo-root", str(repository), "--", "verify"]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
    assert payload["output_limited"] is False
    assert "bounded output capture failed" in captured.err
    assert "host descriptor detail" not in captured.err
    assert "Traceback" not in captured.err


def test_missing_executable_returns_stable_failed_evidence(
    tmp_path: Path,
    capsys,
) -> None:
    """A missing command gives an actionable result instead of a traceback."""

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--",
            "missing-verification-executable",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == sandboxed_verify.COMMAND_NOT_FOUND_EXIT_CODE
    assert payload["exit_code"] == sandboxed_verify.COMMAND_NOT_FOUND_EXIT_CODE
    assert "install the executable or correct command PATH" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize("candidate_kind", ["file", "directory"])
def test_non_executable_command_returns_stable_failed_evidence(
    tmp_path: Path,
    capsys,
    candidate_kind: str,
) -> None:
    """A present but unusable command tells the operator how to recover."""

    candidate = tmp_path / "verification-candidate"
    if candidate_kind == "file":
        candidate.write_text("not executable\n", encoding="utf-8")
    else:
        candidate.mkdir()

    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--",
            str(candidate),
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == sandboxed_verify.COMMAND_NOT_EXECUTABLE_EXIT_CODE
    assert payload["exit_code"] == sandboxed_verify.COMMAND_NOT_EXECUTABLE_EXIT_CODE
    assert "select an executable file or correct its permissions" in captured.err
    assert "Traceback" not in captured.err


def test_unsupported_resource_limit_fails_closed(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    """The wrapper never falls back to unbounded pipes on unsupported platforms."""

    def fail_run(*args, **kwargs):
        del args, kwargs
        raise bounded.OutputLimitUnsupportedError("unsupported")

    monkeypatch.setattr(sandboxed_verify, "run_command", fail_run)
    exit_code = sandboxed_verify.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--output-limit-bytes",
            "4096",
            "--",
            sys.executable,
            "-c",
            "print('never runs')",
        ]
    )
    captured = capsys.readouterr()
    payload = _result_payload(captured.out)

    assert exit_code == bounded.OUTPUT_LIMIT_EXIT_CODE
    assert "bounded child output is unavailable" in captured.err
    assert payload["output_limited"] is False
    assert payload["output_limit_unsupported"] is True


@pytest.mark.parametrize(
    "value",
    ["4095", str(bounded.MAXIMUM_OUTPUT_LIMIT_BYTES + 1)],
)
def test_cli_rejects_output_budgets_outside_supported_range(
    tmp_path: Path,
    value: str,
) -> None:
    """Unsafe output budgets fail argument parsing before workspace execution."""

    repository = _repository(tmp_path)
    with pytest.raises(SystemExit) as raised:
        sandboxed_verify.parse_args(
            [
                "--repo-root",
                str(repository),
                "--output-limit-bytes",
                value,
                "--",
                os.devnull,
            ]
        )
    assert raised.value.code == 2
