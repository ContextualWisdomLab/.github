"""Tests for safe_pytest_command."""

import argparse
import json
import os
import pathlib
import shlex
import subprocess
from unittest import mock

import pytest

from scripts.ci.safe_pytest_command import (
    _basename,
    _has_shell_control,
    _is_pytest_argv,
    _project_python_path,
    discover_commands,
    execute_command,
    main,
    parse_args,
    parse_safe_pytest_command,
)


def test_basename() -> None:
    """Test _basename correctly extracts the posix name."""
    assert _basename("pytest") == "pytest"
    assert _basename("/usr/bin/pytest") == "pytest"
    assert _basename("./venv/bin/pytest") == "pytest"
    assert _basename("dir/script.sh") == "script.sh"


def test_is_pytest_argv() -> None:
    """Test _is_pytest_argv correctly identifies allowed pytest command forms."""
    # Direct pytest
    assert _is_pytest_argv(["pytest"]) is True
    assert _is_pytest_argv(["py.test"]) is True
    assert _is_pytest_argv(["/venv/bin/pytest", "tests/"]) is True

    # Python module
    assert _is_pytest_argv(["python", "-m", "pytest"]) is True
    assert _is_pytest_argv(["python3", "-m", "pytest", "tests/"]) is True
    assert _is_pytest_argv(["/usr/bin/python3", "-m", "pytest"]) is True

    # Coverage module
    assert _is_pytest_argv(["coverage", "run", "-m", "pytest"]) is True
    assert _is_pytest_argv(["/venv/bin/coverage", "run", "-m", "pytest", "tests/"]) is True

    # Invalid
    assert _is_pytest_argv([]) is False
    assert _is_pytest_argv(["bash"]) is False
    assert _is_pytest_argv(["python", "-m", "http.server"]) is False
    assert _is_pytest_argv(["python3"]) is False
    assert _is_pytest_argv(["python3", "-c", "print(1)"]) is False
    assert _is_pytest_argv(["coverage", "report"]) is False


def test_has_shell_control() -> None:
    """Test _has_shell_control identifies shell characters."""
    assert _has_shell_control("rm -rf /") is False
    assert _has_shell_control("pytest") is False
    assert _has_shell_control("test.py") is False

    assert _has_shell_control("pytest;") is True
    assert _has_shell_control("pytest &") is True
    assert _has_shell_control("pytest | wc") is True
    assert _has_shell_control("pytest < input") is True
    assert _has_shell_control("pytest > output") is True
    assert _has_shell_control("pytest `echo`") is True
    assert _has_shell_control("pytest $(echo)") is True


def test_parse_safe_pytest_command() -> None:
    """Test parse_safe_pytest_command validates command parsing."""
    assert parse_safe_pytest_command("pytest") == ["pytest"]
    assert parse_safe_pytest_command("pytest tests/") == ["pytest", "tests/"]
    assert parse_safe_pytest_command("python3 -m pytest") == ["python3", "-m", "pytest"]

    # Should reject invalid forms
    assert parse_safe_pytest_command("bash -c pytest") is None

    # Should reject shell features
    assert parse_safe_pytest_command("pytest && echo") is None
    assert parse_safe_pytest_command("pytest | cat") is None

    # Should reject unclosed quotes (shlex.split ValueError)
    assert parse_safe_pytest_command('pytest "unclosed') is None

    # Should reject control characters
    assert parse_safe_pytest_command("pytest \"\n\" tests/") is None
    assert parse_safe_pytest_command("pytest\x00tests/") is None


def test_discover_commands(tmp_path: pathlib.Path) -> None:
    """Test discover_commands finds valid commands in yaml files."""
    # Test with no directory
    assert discover_commands(tmp_path / "nonexistent") == []

    # Write a valid file
    ci_yml = tmp_path / "ci.yml"
    ci_yml.write_text(
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: pytest tests/1\n"
        "      - run: python3 -m pytest tests/2\n"
        "      - run: bash -c 'echo bad'\n"  # Invalid
        "      - run: pytest tests/1\n"      # Duplicate
    )

    # Write another valid file to ensure it checks all ci.y*ml
    ci_yaml = tmp_path / "ci.yaml"
    ci_yaml.write_text(
        "jobs:\n"
        "      - run: coverage run -m pytest tests/3\n"
    )

    # Write an ignored file
    other_yml = tmp_path / "other.yml"
    other_yml.write_text(
        "jobs:\n"
        "      - run: pytest tests/4\n"
    )

    commands = discover_commands(tmp_path)
    assert commands == [
        ["coverage", "run", "-m", "pytest", "tests/3"],
        ["pytest", "tests/1"],
        ["python3", "-m", "pytest", "tests/2"]
    ]


def test_project_python_path(tmp_path: pathlib.Path) -> None:
    """Test _project_python_path handles src vs flat layouts."""
    # Flat layout
    assert _project_python_path(tmp_path) == "."

    # Src layout
    (tmp_path / "src").mkdir()
    assert _project_python_path(tmp_path) == f"src{os.pathsep}."


@mock.patch("subprocess.run")
def test_execute_command(mock_run: mock.MagicMock, tmp_path: pathlib.Path) -> None:
    """Test execute_command constructs correct subprocess call."""
    # Setup mock
    mock_run.return_value.returncode = 42

    # Mock virtualenv
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)

    # Execute
    env_vars = os.environ.copy()
    env_vars["PYTHONPATH"] = "."
    if "PATH" in env_vars:
        env_vars["PATH"] = f"{venv_bin}{os.pathsep}{env_vars['PATH']}"
    else:
        env_vars["PATH"] = str(venv_bin)

    code = execute_command(tmp_path, ["pytest", "tests/"])
    assert code == 42

    mock_run.assert_called_once_with(
        ["pytest", "tests/"],
        cwd=tmp_path,
        env=mock.ANY,
        shell=False,
        check=False,
    )

    # Verify environment adjustments
    call_env = mock_run.call_args[1]["env"]
    assert call_env["PYTHONPATH"] == "."
    assert call_env["PATH"].startswith(str(venv_bin))

    # Test invalid command raises ValueError
    with pytest.raises(ValueError, match="not a safe direct pytest invocation"):
        execute_command(tmp_path, ["bash", "-c", "pytest"])

    with pytest.raises(ValueError, match="not a safe direct pytest invocation"):
        execute_command(tmp_path, ["pytest", ";", "echo"])


def test_parse_args() -> None:
    """Test parse_args correctly interprets command-line options."""
    args = parse_args(["discover", "--workflow-dir", "/path"])
    assert args.action == "discover"
    assert args.workflow_dir == pathlib.Path("/path")

    args = parse_args(["execute", "--project-dir", "/proj", "--command-json", '["pytest"]'])
    assert args.action == "execute"
    assert args.project_dir == pathlib.Path("/proj")
    assert args.command_json == '["pytest"]'

    with pytest.raises(SystemExit):
        parse_args([])


@mock.patch("scripts.ci.safe_pytest_command.discover_commands")
def test_main_discover(mock_discover: mock.MagicMock, capsys: pytest.CaptureFixture) -> None:
    """Test main function for the discover action."""
    mock_discover.return_value = [["pytest", "tests/1"], ["python", "-m", "pytest"]]

    code = main(["discover", "--workflow-dir", "."])
    assert code == 0

    out, _ = capsys.readouterr()
    assert out == '["pytest","tests/1"]\n["python","-m","pytest"]\n'


@mock.patch("scripts.ci.safe_pytest_command.execute_command")
def test_main_execute(mock_execute: mock.MagicMock, capsys: pytest.CaptureFixture) -> None:
    """Test main function for the execute action."""
    mock_execute.return_value = 0

    code = main(["execute", "--project-dir", ".", "--command-json", '["pytest", "tests/"]'])
    assert code == 0

    out, _ = capsys.readouterr()
    assert "Executing configured pytest argv: pytest tests/" in out

    mock_execute.assert_called_once_with(pathlib.Path("."), ["pytest", "tests/"])


def test_main_execute_invalid_json() -> None:
    """Test main function rejects invalid JSON."""
    with pytest.raises(SystemExit, match="invalid --command-json:"):
        main(["execute", "--project-dir", ".", "--command-json", '{'])


def test_main_execute_invalid_type() -> None:
    """Test main function rejects non-list JSON or lists with non-strings."""
    with pytest.raises(SystemExit, match="--command-json must be an array of strings"):
        main(["execute", "--project-dir", ".", "--command-json", '{"pytest": 1}'])

    with pytest.raises(SystemExit, match="--command-json must be an array of strings"):
        main(["execute", "--project-dir", ".", "--command-json", '["pytest", 1]'])


@mock.patch("subprocess.run")
def test_execute_command_no_path(mock_run: mock.MagicMock, tmp_path: pathlib.Path) -> None:
    """Test execute_command constructs correct subprocess call when PATH is missing."""
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    with mock.patch.dict(os.environ, clear=True):
        execute_command(tmp_path, ["pytest", "tests/"])
    call_env = mock_run.call_args[1]["env"]
    assert call_env["PATH"] == str(venv_bin)

@mock.patch("subprocess.run")
def test_execute_command_no_venv(mock_run: mock.MagicMock, tmp_path: pathlib.Path) -> None:
    """Test execute_command when virtualenv does not exist."""
    execute_command(tmp_path, ["pytest", "tests/"])
    call_env = mock_run.call_args[1]["env"]
    assert "PATH" not in call_env or str(tmp_path) not in call_env.get("PATH", "")




def test_module_execution_subprocess(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the module is executable as a script."""
    # Write a test script that imports and runs it
    script = tmp_path / "run_it.py"
    script.write_text("import scripts.ci.safe_pytest_command\nwith open('scripts/ci/safe_pytest_command.py') as f:\n    exec(compile(f.read(), 'scripts/ci/safe_pytest_command.py', 'exec'), {'__name__': '__main__'})")

    env = os.environ.copy()
    env["COVERAGE_PROCESS_START"] = "pyproject.toml"
    env["PYTHONPATH"] = str(pathlib.Path.cwd())

    result = subprocess.run(
        ["python3", str(script), "discover", "--workflow-dir", str(tmp_path)],
        capture_output=True,
        text=True,
        env=env,
        check=True
    )
    assert result.returncode == 0
