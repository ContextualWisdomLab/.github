"""Real-process contracts for bounded sandbox subprocess output."""

from __future__ import annotations

import io
import os
import sys
import time
from pathlib import Path

import pytest

from scripts.ci import bounded_subprocess as bounded


def _environment() -> dict[str, str]:
    """Return a minimal child environment that can launch the current Python."""

    return {"PATH": os.environ.get("PATH", ""), "PYTHONIOENCODING": "utf-8"}


def test_read_bounded_suffix_preserves_unicode_and_marks_partial_suffix(
    tmp_path: Path,
) -> None:
    """Suffix reads are byte-bounded and tolerate a cut UTF-8 code point."""

    short_path = tmp_path / "short.log"
    short_path.write_text("ordinary 한글\n", encoding="utf-8")
    short = bounded.read_bounded_suffix(short_path, 4096)
    assert short.text == "ordinary 한글\n"
    assert short.truncated is False
    assert short.stored_bytes == len("ordinary 한글\n".encode("utf-8"))

    partial_path = tmp_path / "partial.log"
    partial_path.write_bytes(b"prefix-" + "가".encode("utf-8"))
    partial = bounded.read_bounded_suffix(partial_path, 2)
    assert partial.truncated is True
    assert partial.stored_bytes == len(partial_path.read_bytes())
    assert partial.text.startswith(bounded.TRUNCATION_MARKER)
    assert "�" in partial.text


def test_bounded_capture_retains_final_suffix_and_writes_bounded_file(
    tmp_path: Path,
) -> None:
    """The stream drainer retains only a bounded final suffix for evidence."""

    destination = tmp_path / "captured.log"
    limit_calls: list[str] = []
    capture = bounded.start_bounded_capture(
        io.BytesIO(b"prefix-" + b"x" * 5000 + b"-final"),
        evidence_limit_bytes=4096,
        on_limit=lambda: limit_calls.append("limited"),
        destination=destination,
    )
    capture.join(timeout=5)

    assert capture.output_limited is True
    assert capture.total_bytes == 5013
    assert limit_calls == ["limited"]
    assert capture.text.startswith(bounded.TRUNCATION_MARKER)
    assert capture.text.endswith("-final")
    assert destination.stat().st_size <= 4096
    assert destination.read_text(encoding="utf-8").endswith("-final")


def test_run_bounded_command_preserves_ordinary_unicode_output(tmp_path: Path) -> None:
    """Normal child output and return codes remain unchanged below the budget."""

    result = bounded.run_bounded_command(
        [
            sys.executable,
            "-c",
            "import sys; print('안녕'); print('경고', file=sys.stderr)",
        ],
        cwd=tmp_path,
        env=_environment(),
        timeout=10,
        evidence_limit_bytes=4096,
    )

    assert result.args[0] == sys.executable
    assert result.returncode == 0
    assert result.stdout == "안녕\n"
    assert result.stderr == "경고\n"
    assert result.output_limited is False


def test_run_bounded_command_reaps_descendant_after_direct_child_exits(
    tmp_path: Path,
) -> None:
    """A same-group descendant cannot retain inherited pipes past parent exit."""

    sentinel = tmp_path / "escaped-descendant-ran"
    descendant = (
        "import pathlib,time; "
        "time.sleep(0.75); "
        f"pathlib.Path({str(sentinel)!r}).write_text('escaped', encoding='utf-8')"
    )
    started = time.monotonic()
    result = bounded.run_bounded_command(
        [
            sys.executable,
            "-c",
            (
                "import subprocess,sys; "
                f"subprocess.Popen([sys.executable, '-c', {descendant!r}]); "
                "print('direct child exited')"
            ),
        ],
        cwd=tmp_path,
        env=_environment(),
        timeout=10,
        evidence_limit_bytes=4096,
    )

    assert time.monotonic() - started < 5
    assert result.returncode == 0
    assert result.stdout == "direct child exited\n"
    time.sleep(1)
    assert not sentinel.exists()


def test_capture_text_remains_inside_utf8_byte_budget_after_replacement() -> None:
    """Invalid leading suffix bytes cannot expand retained decoded evidence."""

    capture = bounded.start_bounded_capture(
        io.BytesIO(b"x" * 4095 + b"\xff"),
        evidence_limit_bytes=4096,
        on_limit=lambda: None,
    )
    capture.join(timeout=5)

    assert "�" in capture.text
    assert len(capture.text.encode("utf-8")) <= 4096


@pytest.mark.parametrize("stream_descriptor", [1, 2])
def test_run_bounded_command_caps_real_stdout_and_stderr(
    tmp_path: Path,
    stream_descriptor: int,
) -> None:
    """A real output flood is killed while the retained stream stays bounded."""

    result = bounded.run_bounded_command(
        [
            sys.executable,
            "-c",
            (
                "import os\n"
                f"descriptor={stream_descriptor}\n"
                "chunk=b'x'*1024\n"
                "while True:\n"
                "    os.write(descriptor, chunk)\n"
            ),
        ],
        cwd=tmp_path,
        env=_environment(),
        timeout=10,
        evidence_limit_bytes=4096,
    )

    selected = result.stdout if stream_descriptor == 1 else result.stderr
    assert result.output_limited is True
    assert selected.startswith(bounded.TRUNCATION_MARKER)
    assert len(selected.encode("utf-8")) <= 4096
    assert result.returncode != 0


def test_timeout_raises_with_only_bounded_output(tmp_path: Path) -> None:
    """Timeout evidence is bounded even when the child was actively writing."""

    with pytest.raises(bounded.BoundedTimeoutExpired) as raised:
        bounded.run_bounded_command(
            [
                sys.executable,
                "-c",
                (
                    "import os,time\n"
                    "os.write(1,b'before-timeout\\n')\n"
                    "os.write(2,b'warning-before-timeout\\n')\n"
                    "time.sleep(30)\n"
                ),
            ],
            cwd=tmp_path,
            env=_environment(),
            timeout=1,
            evidence_limit_bytes=4096,
        )

    assert raised.value.timeout == 1
    assert raised.value.stdout == "before-timeout\n"
    assert raised.value.stderr == "warning-before-timeout\n"
    assert raised.value.output_limited is False


def test_validate_output_limit_rejects_unsafe_values() -> None:
    """Configured byte budgets are integer, bounded, and never Boolean."""

    assert bounded.validate_output_limit(4096, "test limit") == 4096
    assert (
        bounded.validate_output_limit(
            bounded.MAXIMUM_OUTPUT_LIMIT_BYTES,
            "test limit",
        )
        == bounded.MAXIMUM_OUTPUT_LIMIT_BYTES
    )
    for value in [
        True,
        1.5,
        "4096",
        4095,
        bounded.MAXIMUM_OUTPUT_LIMIT_BYTES + 1,
    ]:
        with pytest.raises(ValueError, match="test limit"):
            bounded.validate_output_limit(value, "test limit")  # type: ignore[arg-type]


def test_supported_platform_gate_fails_closed(monkeypatch) -> None:
    """Unsupported platforms cannot silently fall back to unmanaged children."""

    monkeypatch.setattr(bounded.os, "name", "nt")
    with pytest.raises(bounded.OutputLimitUnsupportedError):
        bounded.require_supported_platform()

    monkeypatch.setattr(bounded.os, "name", "posix")
    bounded.require_supported_platform()


def test_capture_surfaces_reader_failure_and_join_timeout(
    monkeypatch,
) -> None:
    """Reader failures and stuck drains are explicit rather than silently ignored."""

    class FailingStream:
        """Raise one deterministic error from the background reader."""

        def read(self, size: int) -> bytes:
            """Reject the read request."""

            del size
            raise OSError("read failed")

        def close(self) -> None:
            """Provide the binary-stream close interface."""

    capture = bounded.start_bounded_capture(
        FailingStream(),  # type: ignore[arg-type]
        evidence_limit_bytes=4096,
        on_limit=lambda: None,
    )
    with pytest.raises(OSError, match="read failed"):
        capture.join(timeout=5)

    class NeverFinishesThread:
        """Simulate one drain thread that remains alive after join."""

        def join(self, timeout: float | None = None) -> None:
            """Accept the join call without completing."""

            del timeout

        def is_alive(self) -> bool:
            """Report a stuck reader."""

            return True

    capture = bounded.BoundedOutputCapture(
        io.BytesIO(b"safe"),
        evidence_limit_bytes=4096,
        on_limit=lambda: None,
    )
    assert capture.stream is capture._stream  # noqa: SLF001 - ownership contract
    monkeypatch.setattr(capture, "_thread", NeverFinishesThread())
    with pytest.raises(RuntimeError, match="did not finish"):
        capture.join(timeout=0)


def test_join_captures_applies_finite_timeout_and_joins_every_reader() -> None:
    """Normal-path capture finalization cannot wait forever on inherited pipe FDs."""

    observed: list[tuple[str, float]] = []

    class Capture:
        """Record the timeout and optionally expose one stuck-reader failure."""

        def __init__(self, label: str, *, fail: bool = False) -> None:
            self.label = label
            self.fail = fail

        def join(self, timeout: float) -> None:
            """Require a positive finite timeout and retain sibling finalization."""

            observed.append((self.label, timeout))
            if self.fail:
                raise RuntimeError("bounded output drain did not finish")

    with pytest.raises(RuntimeError, match="did not finish"):
        bounded._join_captures(  # noqa: SLF001 - internal safety contract
            (Capture("first", fail=True), Capture("second", fail=True))  # type: ignore[arg-type]
        )

    assert [label for label, _timeout in observed] == ["first", "second"]
    assert all(timeout > 0 for _label, timeout in observed)
    assert len({timeout for _label, timeout in observed}) == 1


def test_run_bounded_command_rejects_empty_command_and_timeout(tmp_path: Path) -> None:
    """The reusable runner validates execution controls before creating children."""

    with pytest.raises(ValueError, match="command"):
        bounded.run_bounded_command(
            [],
            cwd=tmp_path,
            env=_environment(),
            timeout=10,
            evidence_limit_bytes=4096,
        )
    with pytest.raises(ValueError, match="timeout"):
        bounded.run_bounded_command(
            [sys.executable, "-c", "pass"],
            cwd=tmp_path,
            env=_environment(),
            timeout=0,
            evidence_limit_bytes=4096,
        )
