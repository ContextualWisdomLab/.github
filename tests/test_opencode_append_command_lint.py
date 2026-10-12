"""Keep command-summary publication byte-exact with one append open."""

import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[1] / ".github/workflows/opencode-review-dispatch.yml"


def _append_function():
    """Read the complete shipped shell function, not a replacement fixture."""
    text = WORKFLOW.read_text(encoding="utf-8")
    start = text.index("          append_command() {")
    end = text.index("\n          emit_captured_log() {", start)
    return text[start:end]


def test_command_summary_opens_destination_once():
    """One enclosing redirection avoids separate command-summary opens."""
    assert _append_function().count('>>"$summary_file"') == 1


@pytest.mark.parametrize("args", [
    [], ["simple"], ["space value", "", "*"],
    ["'quote'", '"double"', "$literal", "`literal`"],
    ["newline\nvalue", "tab\tvalue", "한글"],
])
def test_command_summary_preserves_exact_escaped_bytes(tmp_path, args):
    """Native Bash percent-q output and an existing prefix remain intact."""
    summary = tmp_path / "summary"
    summary.write_bytes(b"existing\n")
    result = subprocess.run(
        ["bash", "-c", 'summary_file="$1"; shift\n' + _append_function() + '\nappend_command "$@"', "bash", str(summary), *args],
        capture_output=True, timeout=10,
    )
    expected = subprocess.run(
        ["bash", "-c", "printf '$ '; printf '%q ' \"$@\"; printf '\\n'", "bash", *args],
        capture_output=True, timeout=10,
    )
    assert result.returncode == expected.returncode == 0
    assert result.stderr == b""
    assert summary.read_bytes() == b"existing\n" + expected.stdout


def test_command_summary_refuses_directory_destination(tmp_path):
    """An unopenable destination rejects publication without invoking printf."""
    result = subprocess.run(
        ["bash", "-c", 'summary_file="$1"\n' + _append_function() + '\nappend_command sentinel', "bash", str(tmp_path)],
        capture_output=True, timeout=10,
    )
    assert result.returncode != 0
    assert result.stdout == b""
    assert not list(tmp_path.iterdir())
