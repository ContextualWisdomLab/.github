"""Tests for the changed-file syntax gate."""

from __future__ import annotations

import runpy
import subprocess
import sys
import pytest

from scripts.ci import changed_file_syntax_gate as gate


def write(tmp_path, name, content):
    """Write a file under tmp_path and return its path."""
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_check_python_accepts_valid_and_rejects_invalid(tmp_path):
    """Valid Python parses; a syntax error is reported with its line."""
    good = write(tmp_path, "good.py", "def f():\n    return 1\n")
    bad = write(tmp_path, "bad.py", "def f(:\n    return 1\n")

    assert gate.check_python(good) == (gate.OK, "")
    result, detail = gate.check_python(bad)
    assert result == gate.FAILED
    assert "line" in detail


def test_check_with_command_skips_when_tool_missing(tmp_path, monkeypatch):
    """A missing toolchain skips (never fails) the file."""
    monkeypatch.setattr(gate.shutil, "which", lambda tool: None)
    result, detail = gate.check_with_command("node", ["node", "--check", "x"], tmp_path)
    assert result == gate.SKIPPED
    assert "not available" in detail


def test_check_with_command_reports_ok_and_failure(tmp_path, monkeypatch):
    """A present tool returns ok on success and failed on non-zero exit."""
    monkeypatch.setattr(gate.shutil, "which", lambda tool: "/usr/bin/" + tool)

    def fake_run_ok(cmd, **kwargs):
        assert kwargs["timeout"] == gate.COMMAND_TIMEOUT_SECONDS
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(gate.subprocess, "run", fake_run_ok)
    assert gate.check_with_command("node", ["node"], tmp_path) == (gate.OK, "")

    def fake_run_fail(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="Unexpected token }")

    monkeypatch.setattr(gate.subprocess, "run", fake_run_fail)
    result, detail = gate.check_with_command("node", ["node"], tmp_path)
    assert result == gate.FAILED
    assert "Unexpected token" in detail


def test_check_with_command_skips_when_tool_times_out(tmp_path, monkeypatch):
    """A hung syntax tool is skipped with an explicit reason."""
    monkeypatch.setattr(gate.shutil, "which", lambda tool: "/usr/bin/" + tool)

    def fake_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    monkeypatch.setattr(gate.subprocess, "run", fake_timeout)
    result, detail = gate.check_with_command("bash", ["bash"], tmp_path)
    assert result == gate.SKIPPED
    assert "timed out after" in detail


def test_check_with_command_detail_fallbacks(tmp_path, monkeypatch):
    """Failure detail falls back to stdout, then a generic message."""
    monkeypatch.setattr(gate.shutil, "which", lambda tool: "/usr/bin/" + tool)

    def stdout_only(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="parse error here", stderr="")

    monkeypatch.setattr(gate.subprocess, "run", stdout_only)
    _, detail = gate.check_with_command("bash", ["bash"], tmp_path)
    assert detail == "parse error here"

    def empty_output(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="")

    monkeypatch.setattr(gate.subprocess, "run", empty_output)
    _, detail = gate.check_with_command("bash", ["bash"], tmp_path)
    assert "reported a syntax error" in detail


def test_check_shell_uses_bash_n(tmp_path):
    """A real bash -n check flags a broken shell script when bash exists."""
    bad = write(tmp_path, "bad.sh", "if then fi\n")
    if gate.shutil.which("bash") is None:  # pragma: no cover - CI always has bash
        pytest.skip("bash not available")
    result, detail = gate.check_shell(bad)
    if result == gate.SKIPPED and "timed out after" in detail:
        pytest.skip(detail)
    assert result == gate.FAILED
    good = write(tmp_path, "good.sh", "echo hello\n")
    assert gate.check_shell(good) == (gate.OK, "")


def test_check_javascript_dispatch(tmp_path, monkeypatch):
    """check_javascript routes through node --check."""
    calls = {}

    def fake(tool, command, path):
        calls["tool"] = tool
        calls["command"] = command
        return (gate.OK, "")

    monkeypatch.setattr(gate, "check_with_command", fake)
    assert gate.check_javascript(tmp_path / "a.js") == (gate.OK, "")
    assert calls["tool"] == "node"
    assert calls["command"][:2] == ["node", "--check"]


def test_check_changed_file_skips_missing_and_unknown(tmp_path):
    """Deleted paths and unrecognized extensions are skipped, not failed."""
    missing, _ = gate.check_changed_file(tmp_path / "gone.py")
    assert missing == gate.SKIPPED
    unknown = write(tmp_path, "notes.rs", "fn main() {")
    result, detail = gate.check_changed_file(unknown)
    assert result == gate.SKIPPED
    assert "no unambiguous" in detail


def test_check_changed_file_dispatches_python(tmp_path):
    """A known extension dispatches to its checker."""
    bad = write(tmp_path, "bad.py", "x = (")
    result, _ = gate.check_changed_file(bad)
    assert result == gate.FAILED


def test_read_changed_files_ignores_blank_lines(tmp_path):
    """Blank and whitespace-only lines are dropped."""
    listing = write(tmp_path, "changed.txt", "a.py\n\n  \n b.py \n")
    assert gate.read_changed_files(listing) == ["a.py", "b.py"]


def test_run_gate_aggregates_results(tmp_path):
    """run_gate returns failures plus checked and skipped counts."""
    good = write(tmp_path, "good.py", "x = 1\n")
    bad = write(tmp_path, "bad.py", "x = (\n")
    skipped = write(tmp_path, "data.rs", "??")
    failures, checked, skipped_count = gate.run_gate(
        [str(good), str(bad), str(skipped), str(tmp_path / "missing.py")]
    )
    assert checked == 2
    assert skipped_count == 2
    assert len(failures) == 1
    assert failures[0][0] == str(bad)


def test_format_report_lists_failures():
    """The report names each failing file and the counts."""
    report = gate.format_report([("bad.py", "invalid syntax (line 1)")], 3, 1)
    assert "3 checked, 1 skipped, 1 failed" in report
    assert "SYNTAX ERROR bad.py" in report
    clean = gate.format_report([], 2, 0)
    assert "0 failed" in clean


def test_main_returns_zero_when_clean(tmp_path, capsys):
    """main exits 0 when no changed file has a syntax error."""
    good = write(tmp_path, "good.py", "x = 1\n")
    listing = write(tmp_path, "changed.txt", f"{good}\n")
    assert gate.main(["--changed-files-file", str(listing)]) == 0
    assert "0 failed" in capsys.readouterr().out


def test_main_returns_one_on_syntax_error(tmp_path, capsys):
    """main exits 1 and reports the offending file on a syntax error."""
    bad = write(tmp_path, "bad.py", "def broken(:\n")
    listing = write(tmp_path, "changed.txt", f"{bad}\n")
    assert gate.main(["--changed-files-file", str(listing)]) == 1
    assert "SYNTAX ERROR" in capsys.readouterr().out


def test_module_entrypoint_invokes_main(tmp_path, monkeypatch):
    """Exercise the __main__ entrypoint used by the workflow step."""
    good = write(tmp_path, "good.py", "x = 1\n")
    listing = write(tmp_path, "changed.txt", f"{good}\n")
    monkeypatch.setattr(
        sys,
        "argv",
        ["changed_file_syntax_gate.py", "--changed-files-file", str(listing)],
    )
    with pytest.raises(SystemExit) as excinfo:
        runpy.run_path(gate.__file__, run_name="__main__")
    assert excinfo.value.code == 0
