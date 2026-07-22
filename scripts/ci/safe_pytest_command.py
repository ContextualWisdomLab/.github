#!/usr/bin/env python3
"""Discover and execute configured pytest commands without a shell."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import stat
from collections.abc import Sequence

RUN_LINE_RE = re.compile(r"\s*(?:-\s*)?run:\s*(.+?)\s*$")
PYTEST_EXECUTABLES = frozenset({"pytest", "py.test"})
PYTHON_EXECUTABLES = frozenset({"python", "python3"})
TRUSTED_PYTHON_ENV_ROOT = pathlib.Path("/opt/base-python-envs")
TRUSTED_PYTHON_ENV_OWNER_UID = 0


def _is_pytest_argv(argv: Sequence[str]) -> bool:
    """Return whether argv is a supported direct pytest invocation."""
    if not argv:
        return False
    executable = argv[0]
    if "/" in executable or "\\" in executable:
        return False
    if executable in PYTEST_EXECUTABLES:
        return True
    if executable in PYTHON_EXECUTABLES:
        return len(argv) >= 3 and argv[1:3] == ["-m", "pytest"]
    if executable == "coverage":
        return len(argv) >= 4 and argv[1:4] == ["run", "-m", "pytest"]
    return False


def _has_shell_control(value: str) -> bool:
    """Return whether one argv token contains shell control syntax."""
    return any(character in value for character in ";&|<>`") or "$(" in value


def parse_safe_pytest_command(command: str) -> list[str] | None:
    """Parse a supported command into argv, rejecting shell control syntax."""
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if not argv or any(
        "\n" in arg or "\x00" in arg or _has_shell_control(arg) for arg in argv
    ):
        return None
    return argv if _is_pytest_argv(argv) else None


def discover_commands(workflow_dir: pathlib.Path) -> list[list[str]]:
    """Return unique safe one-line pytest argv from ci.yml/ci.yaml files."""
    commands: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    if not workflow_dir.is_dir():
        return commands
    for path in sorted(workflow_dir.glob("ci.y*ml")):
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            match = RUN_LINE_RE.fullmatch(line)
            if match is None:
                continue
            argv = parse_safe_pytest_command(match.group(1).strip())
            key = tuple(argv or ())
            if not argv or key in seen:
                continue
            seen.add(key)
            commands.append(argv)
    return commands


def execute_command(project_dir: pathlib.Path, argv: Sequence[str]) -> int:
    """Execute validated pytest argv directly in one project directory."""
    if not _is_pytest_argv(argv) or any(_has_shell_control(arg) for arg in argv):
        raise ValueError("configured command is not a safe direct pytest invocation")
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    supplied_env_bin = os.environ.get("OPENCODE_PYTHON_ENV_BIN", "").strip()
    trusted_bin: pathlib.Path | None = None
    if supplied_env_bin:
        candidate = pathlib.Path(supplied_env_bin)
        try:
            resolved = candidate.resolve(strict=True)
            candidate_stat = resolved.stat()
            trusted_root = TRUSTED_PYTHON_ENV_ROOT.resolve(strict=True)
        except OSError as exc:
            raise ValueError("trusted Python environment path is unavailable") from exc
        if (
            not resolved.is_dir()
            or trusted_root not in resolved.parents
            or candidate_stat.st_uid != TRUSTED_PYTHON_ENV_OWNER_UID
            or candidate_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        ):
            raise ValueError("trusted Python environment path failed validation")
        trusted_bin = resolved

    search_path = str(trusted_bin) if trusted_bin is not None else env.get("PATH", "")
    executable_path = shutil.which(argv[0], path=search_path)
    if not executable_path:
        raise ValueError("configured pytest executable is unavailable from the trusted PATH")
    candidate_executable = pathlib.Path(executable_path)
    if not candidate_executable.is_absolute():
        raise ValueError("configured pytest executable must resolve to an absolute path")
    try:
        candidate_absolute = candidate_executable.absolute()
        resolved_executable = candidate_executable.resolve(strict=True)
        candidate_stat = candidate_executable.lstat()
        resolved_stat = resolved_executable.stat()
        project_root = project_dir.resolve(strict=True)
    except OSError as exc:
        raise ValueError("configured pytest executable path is unavailable") from exc
    if (
        not resolved_executable.is_file()
        or not os.access(resolved_executable, os.X_OK)
        or candidate_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or resolved_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or candidate_absolute == project_root
        or project_root in candidate_absolute.parents
        or resolved_executable == project_root
        or project_root in resolved_executable.parents
    ):
        raise ValueError("configured pytest executable failed trust validation")
    if trusted_bin is not None:
        if (
            candidate_absolute.parent != trusted_bin
            or candidate_stat.st_uid != TRUSTED_PYTHON_ENV_OWNER_UID
        ):
            raise ValueError("trusted Python environment executable failed validation")
        env["PATH"] = str(trusted_bin)

    command = [str(resolved_executable), *argv[1:]]
    completed = subprocess.run(
        command,
        cwd=project_dir,
        env=env,
        shell=False,
        check=False,
    )
    return completed.returncode


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse discovery or execution arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--workflow-dir", required=True, type=pathlib.Path)
    execute = subparsers.add_parser("execute")
    execute.add_argument("--project-dir", required=True, type=pathlib.Path)
    execute.add_argument("--command-json", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run configured-command discovery or shell-free execution."""
    args = parse_args(argv)
    if args.action == "discover":
        for command in discover_commands(args.workflow_dir):
            print(json.dumps(command, separators=(",", ":")))
        return 0
    try:
        command = json.loads(args.command_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"invalid --command-json: {exc}") from exc
    if not isinstance(command, list) or not all(
        isinstance(arg, str) for arg in command
    ):
        raise SystemExit("--command-json must be an array of strings")
    print(f"Executing configured pytest argv: {shlex.join(command)}")
    return execute_command(args.project_dir, command)


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
