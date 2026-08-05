#!/usr/bin/env python3
"""Apply test-first final review repairs for PR 767."""

from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOUNDED = ROOT / "scripts/ci/bounded_subprocess.py"
REDACTOR = ROOT / "scripts/ci/redact_sensitive_log.py"
WEB = ROOT / "scripts/ci/sandboxed_web_e2e.py"
TEST_BOUNDED = ROOT / "tests/test_bounded_subprocess.py"
TEST_REDACTOR = ROOT / "tests/test_redact_sensitive_log_contract.py"
TEST_ENTRYPOINT = ROOT / "tests/test_sandboxed_entrypoint_and_cleanup_coverage.py"
TEST_WEB = ROOT / "tests/test_sandboxed_web_e2e.py"
TEST_WEB_LIMITS = ROOT / "tests/test_sandboxed_web_e2e_output_limits.py"
CHANGELOG = ROOT / "CHANGELOG.md"
WORKFLOW = ROOT / ".github/workflows/finalize-pr767-review-repairs.yml"
SCRIPT = Path(__file__).resolve()


def replace_once(path: Path, old: str, new: str) -> None:
    """Replace exactly one audited UTF-8 fragment."""
    source = path.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"expected one anchor in {path}, found {count}: {old[:100]!r}")
    path.write_text(source.replace(old, new, 1), encoding="utf-8")


def append_once(path: Path, marker: str, addition: str) -> None:
    """Append one regression block when its marker is absent."""
    source = path.read_text(encoding="utf-8")
    if marker in source:
        raise SystemExit(f"regression already exists in {path}: {marker}")
    path.write_text(source + addition, encoding="utf-8")


def add_tests() -> None:
    """Add regressions that fail against the uncorrected production contracts."""
    append_once(
        TEST_BOUNDED,
        "test_join_captures_applies_finite_timeout_and_finishes_siblings",
        r'''


def test_join_captures_applies_finite_timeout_and_finishes_siblings() -> None:
    """Every reader receives a finite join bound and siblings still finalize."""

    calls: list[tuple[str, float | None]] = []

    class Capture:
        """Record the supplied timeout and optionally fail."""

        def __init__(self, name: str, error: BaseException | None = None) -> None:
            self.name = name
            self.error = error

        def join(self, timeout: float | None = None) -> None:
            calls.append((self.name, timeout))
            if self.error is not None:
                raise self.error

    with pytest.raises(RuntimeError, match="first reader failed"):
        bounded._join_captures(  # noqa: SLF001 - focused internal contract
            [Capture("first", RuntimeError("first reader failed")), Capture("second")]
        )

    assert calls == [
        ("first", bounded.READER_JOIN_TIMEOUT_SECONDS),
        ("second", bounded.READER_JOIN_TIMEOUT_SECONDS),
    ]
''',
    )
    append_once(
        TEST_REDACTOR,
        "test_bare_sensitive_word_does_not_consume_the_next_argument",
        r'''


def test_bare_sensitive_word_does_not_consume_the_next_argument() -> None:
    """Only dash-prefixed options treat the following argument as a value."""

    assert redactor.redact_command_arguments(
        ["docker", "run", "-e", "TOKEN", "image"]
    ) == ["docker", "run", "-e", "TOKEN", "image"]
    assert redactor.redact_command_arguments(
        ["tool", "TOKEN=value", "image"]
    ) == ["tool", "TOKEN=[REDACTED]", "image"]
''',
    )
    replace_once(
        TEST_ENTRYPOINT,
        "import runpy\nimport subprocess\nimport sys\n",
        "import runpy\nimport sys\n",
    )
    replace_once(
        TEST_ENTRYPOINT,
        '''        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=["e2e"],
            returncode=0,
            stdout="ok\\n",
            stderr="",
        ),
''',
        '''        lambda *args, **kwargs: bounded_subprocess.BoundedCompletedProcess(
            args=("e2e",),
            returncode=0,
            stdout="ok\\n",
            stderr="",
            output_limited=False,
        ),
''',
    )
    replace_once(
        TEST_ENTRYPOINT,
        '        raise OSError(f"cannot finalize {service.label}")\n',
        '        raise ValueError(f"cannot finalize {service.label}")\n',
    )
    replace_once(
        TEST_WEB,
        '''        lambda command, cwd, env, timeout, output_limit_bytes=sandboxed_web_e2e.bounded_subprocess.DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES: subprocess.CompletedProcess(
            command,
            0,
            stdout="e2e-out\\n",
            stderr="e2e-err\\n",
        ),
''',
        '''        lambda command, cwd, env, timeout, output_limit_bytes=sandboxed_web_e2e.bounded_subprocess.DEFAULT_COMMAND_OUTPUT_LIMIT_BYTES: sandboxed_web_e2e.bounded_subprocess.BoundedCompletedProcess(
            args=("e2e",),
            returncode=0,
            stdout="e2e-out\\n",
            stderr="e2e-err\\n",
            output_limited=False,
        ),
''',
    )
    replace_once(
        TEST_WEB_LIMITS,
        '''    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            _command(
                "import os\\n"
                "chunk=b'x'*1024\\n"
                "while True:\\n"
                "    os.write(1,chunk)\\n"
            ),
            "--frontend-cmd",
            _command("import time; time.sleep(30)"),
            "--e2e-cmd",
            _command("raise SystemExit('must not run')"),
            "--service-log-limit-bytes",
            "4096",
        ]
    )
''',
        '''    sentinel = tmp_path / "e2e-ran"
    exit_code = sandboxed_web_e2e.main(
        [
            "--repo-root",
            str(_repository(tmp_path)),
            "--backend-cmd",
            _command(
                "import os\\n"
                "chunk=b'x'*1024\\n"
                "while True:\\n"
                "    os.write(1,chunk)\\n"
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
''',
    )
    replace_once(
        TEST_WEB_LIMITS,
        '''    assert payload["output_limited"] is True
    assert payload["service_log_limit_bytes"] == 4096


def test_e2e_output_overflow_is_bounded_and_returns_123(
''',
        '''    assert payload["output_limited"] is True
    assert payload["service_log_limit_bytes"] == 4096
    assert not sentinel.exists()


def test_e2e_output_overflow_is_bounded_and_returns_123(
''',
    )


def apply_repair() -> None:
    """Apply the bounded reader, redaction, and cleanup corrections."""
    replace_once(
        BOUNDED,
        'READ_CHUNK_BYTES = 65_536\nTRUNCATION_MARKER = "...[output truncated]...\\n"\n',
        'READ_CHUNK_BYTES = 65_536\nREADER_JOIN_TIMEOUT_SECONDS = 30.0\nTRUNCATION_MARKER = "...[output truncated]...\\n"\n',
    )
    replace_once(
        BOUNDED,
        '''def _join_captures(captures: Sequence[BoundedOutputCapture]) -> None:
    """Finalize every stream reader while preserving the first reported failure."""

    first_error: BaseException | None = None
    for capture in captures:
        try:
            capture.join()
        except BaseException as error:  # noqa: BLE001 - re-raised after sibling join
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error
''',
        '''def _join_captures(
    captures: Sequence[BoundedOutputCapture],
    timeout: float = READER_JOIN_TIMEOUT_SECONDS,
) -> None:
    """Finalize every stream reader within a finite bound, preserving the first failure."""

    first_error: BaseException | None = None
    for capture in captures:
        try:
            capture.join(timeout)
        except BaseException as error:  # noqa: BLE001 - re-raised after sibling join
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error
''',
    )
    replace_once(
        REDACTOR,
        '''        option = argument.lstrip("-")
        if "=" in option:
''',
        '''        is_option = argument.startswith("-")
        option = argument.lstrip("-")
        if "=" in option:
''',
    )
    replace_once(
        REDACTOR,
        '''        redacted.append(redact_text(argument))
        if SENSITIVE_OPTION_RE.fullmatch(option):
            redact_next = True
''',
        '''        redacted.append(redact_text(argument))
        if is_option and SENSITIVE_OPTION_RE.fullmatch(option):
            redact_next = True
''',
    )
    replace_once(
        WEB,
        '''            except (OSError, RuntimeError, subprocess.SubprocessError):
                output_limited = True
''',
        '''            except Exception:  # noqa: BLE001 - cleanup must not skip result emission
                output_limited = True
''',
    )
    text = CHANGELOG.read_text(encoding="utf-8")
    additions = [
        "- Bound normal-path stdout/stderr reader joins so inherited pipe descriptors cannot hold a sandbox job indefinitely.\n",
        "- Preserve ordinary command arguments after bare credential-shaped words while retaining dash-prefixed option and assignment redaction.\n",
        "- Continue sandbox result emission and directory cleanup after any ordinary service-capture finalization exception.\n",
    ]
    marker = "### Fixed\n\n"
    if marker not in text:
        raise SystemExit("CHANGELOG Fixed section missing")
    for addition in reversed(additions):
        if addition not in text:
            text = text.replace(marker, marker + addition, 1)
    CHANGELOG.write_text(text, encoding="utf-8")


def cleanup() -> None:
    """Remove the temporary exact-head workflow and helper."""
    WORKFLOW.unlink()
    SCRIPT.unlink()


def main() -> None:
    """Execute one deterministic repair phase."""
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("add-tests", "apply", "cleanup"))
    args = parser.parse_args()
    if args.phase == "add-tests":
        add_tests()
    elif args.phase == "apply":
        apply_repair()
    else:
        cleanup()


if __name__ == "__main__":
    main()
