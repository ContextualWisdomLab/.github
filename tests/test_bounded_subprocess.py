"""Real-process contracts for bounded sandbox subprocess output."""

from __future__ import annotations

import os
import signal
import sys
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
    assert len(partial.text.removeprefix(bounded.TRUNCATION_MARKER).encode("utf-8")) <= 6


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


@pytest.mark.parametrize("stream_descriptor", [1, 2])
def test_run_bounded_command_caps_real_stdout_and_stderr(
    tmp_path: Path,
    stream_descriptor: int,
) -> None:
    """A child cannot create a captured stream beyond budget plus one byte."""

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
    assert len(selected.encode("utf-8")) <= 4096 + len(
        bounded.TRUNCATION_MARKER.encode("utf-8")
    )
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


def test_preexec_fails_closed_without_posix_resource_support(monkeypatch) -> None:
    """Unsupported platforms cannot silently fall back to unbounded capture."""

    monkeypatch.setattr(bounded.os, "name", "nt")
    with pytest.raises(bounded.OutputLimitUnsupportedError):
        bounded.bounded_file_preexec(4096)

    monkeypatch.setattr(bounded.os, "name", "posix")
    monkeypatch.setattr(bounded, "_resource", None)
    with pytest.raises(bounded.OutputLimitUnsupportedError):
        bounded.bounded_file_preexec(4096)


def test_preexec_respects_a_lower_existing_hard_limit(monkeypatch) -> None:
    """The child limit is lowered but an existing hard limit is never raised."""

    class FakeResource:
        """Record the limit selected by the child pre-exec closure."""

        RLIMIT_FSIZE = 1
        RLIM_INFINITY = -1

        def __init__(self, hard_limit: int) -> None:
            self.hard_limit = hard_limit
            self.applied: tuple[int, tuple[int, int]] | None = None

        def getrlimit(self, resource_name: int) -> tuple[int, int]:
            """Return the configured finite hard limit."""

            assert resource_name == self.RLIMIT_FSIZE
            return (self.hard_limit, self.hard_limit)

        def setrlimit(
            self,
            resource_name: int,
            limits: tuple[int, int],
        ) -> None:
            """Record the exact child limits."""

            self.applied = (resource_name, limits)

    finite = FakeResource(2048)
    monkeypatch.setattr(bounded.os, "name", "posix")
    monkeypatch.setattr(bounded, "_resource", finite)
    bounded.bounded_file_preexec(4096)()
    assert finite.applied == (finite.RLIMIT_FSIZE, (2048, 2048))

    unlimited = FakeResource(FakeResource.RLIM_INFINITY)
    monkeypatch.setattr(bounded, "_resource", unlimited)
    bounded.bounded_file_preexec(4096)()
    assert unlimited.applied == (unlimited.RLIMIT_FSIZE, (4097, 4097))


def test_file_limit_classification_uses_size_signal_and_safe_false_path(
    tmp_path: Path,
) -> None:
    """Overflow classification remains deterministic across child behaviors."""

    output_path = tmp_path / "output.log"
    output_path.write_bytes(b"x" * 4097)
    assert bounded.file_limit_reached(output_path, 4096, 0)

    output_path.write_bytes(b"x" * 10)
    assert bounded.file_limit_reached(
        output_path,
        4096,
        -int(signal.SIGXFSZ),
    )
    assert not bounded.file_limit_reached(output_path, 4096, 0)


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
