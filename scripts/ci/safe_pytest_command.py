#!/usr/bin/env python3
"""Discover and execute configured pytest commands without a shell."""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shlex
import subprocess
from collections.abc import Sequence

RUN_LINE_RE = re.compile(r"\s*(?:-\s*)?run:\s*(.+?)\s*$")
PYTEST_EXECUTABLES = frozenset({"pytest", "py.test"})
PYTHON_EXECUTABLES = frozenset({"python", "python3"})


def _basename(value: str) -> str:
    """Return a command token's POSIX basename."""
    return pathlib.PurePosixPath(value).name


def _is_pytest_argv(argv: Sequence[str]) -> bool:
    """Return whether argv is a supported direct pytest invocation."""
    if not argv:
        return False
    executable = _basename(argv[0])
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
    if not argv or any("\n" in arg or "\x00" in arg or _has_shell_control(arg) for arg in argv):
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


def _repository_package_python_paths(project_dir: pathlib.Path) -> list[str]:
    """Return trusted sibling package ``src`` paths from the nearest monorepo.

    The coverage sandbox intentionally replaces, rather than extends, the
    inherited ``PYTHONPATH``. A project such as ``services/people-api`` can
    still import its repository-owned packages when their ``src`` directories
    are discovered beneath the nearest ancestor ``packages`` directory.
    Symlinked package paths are excluded so this discovery cannot widen the
    sandbox through a path controlled by a checkout link.
    """
    resolved_project = project_dir.resolve()
    for repository_root in (resolved_project, *resolved_project.parents):
        packages_dir = repository_root / "packages"
        if not packages_dir.is_dir() or packages_dir.is_symlink():
            continue
        resolved_packages_dir = packages_dir.resolve()
        package_sources: list[str] = []
        for package_dir in sorted(packages_dir.iterdir()):
            if not package_dir.is_dir() or package_dir.is_symlink():
                continue
            source_dir = package_dir / "src"
            if not source_dir.is_dir() or source_dir.is_symlink():
                continue
            resolved_source_dir = source_dir.resolve()
            if resolved_source_dir.is_relative_to(resolved_packages_dir):
                package_sources.append(str(resolved_source_dir))
        if package_sources:
            return package_sources
    return []


def _project_python_path(project_dir: pathlib.Path) -> str:
    """Return local and trusted sibling package paths for a project.

    Repositories that keep their importable package under ``src/`` (a
    ``src``-layout such as ``src/<package>``) cannot import it with the project
    root alone on the path, so an offline coverage run started from the project
    root fails at collection with ``ModuleNotFoundError``. When a ``src``
    directory exists it is prepended to the path. Repository-owned sibling
    package ``src`` directories are then added for monorepo projects; otherwise
    the path remains the local project root, preserving the previous behavior.
    """
    entries = ["."]
    if (project_dir / "src").is_dir():
        entries.insert(0, "src")
    return os.pathsep.join((*entries, *_repository_package_python_paths(project_dir)))


def execute_command(project_dir: pathlib.Path, argv: Sequence[str]) -> int:
    """Execute validated pytest argv directly in one project directory."""
    if not _is_pytest_argv(argv) or any(_has_shell_control(arg) for arg in argv):
        raise ValueError("configured command is not a safe direct pytest invocation")
    env = os.environ.copy()
    env["PYTHONPATH"] = _project_python_path(project_dir)
    virtualenv_bin = project_dir.resolve() / ".venv" / "bin"
    if virtualenv_bin.is_dir():
        inherited_path = env.get("PATH")
        env["PATH"] = (
            os.pathsep.join((str(virtualenv_bin), inherited_path))
            if inherited_path
            else str(virtualenv_bin)
        )
    completed = subprocess.run(
        list(argv),
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
    if not isinstance(command, list) or not all(isinstance(arg, str) for arg in command):
        raise SystemExit("--command-json must be an array of strings")
    print(f"Executing configured pytest argv: {shlex.join(command)}")
    return execute_command(args.project_dir, command)


if __name__ == "__main__":
    raise SystemExit(main())
