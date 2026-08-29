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

RUN_KEY_RE = re.compile(r"^(?P<indent>\s*)(?:-\s*)?run:\s*(?P<rest>.*)$")
BLOCK_SCALAR_HEADER_RE = re.compile(
    r"^[|>](?:[+-]?[1-9]?|[1-9]?[+-]?)\s*(?:#.*)?$"
)
PYTEST_EXECUTABLES = frozenset({"pytest", "py.test"})
PYTHON_EXECUTABLES = frozenset({"python", "python3"})
PYTHON_VERSIONED_RE = re.compile(r"^python3\.\d+$")
PYTHON_FLAG_TAKES_VALUE = frozenset({"-W", "-X", "--check-hash-based-pycs"})
COVERAGE_RUN_FLAG_TAKES_VALUE = frozenset(
    {
        "--source",
        "--data-file",
        "--rcfile",
        "--include",
        "--omit",
        "--concurrency",
        "--context",
        "--debug",
    }
)


def _basename(value: str) -> str:
    """Return a command token's POSIX basename."""
    return pathlib.PurePosixPath(value).name


MODULE_TARGET_TOKENS = frozenset({"-m", "--module"})
FORBIDDEN_EXECUTION_TOKENS = frozenset({"-c", "-", "--"})


def _skip_flag_tokens(
    argv: Sequence[str],
    index: int,
    *,
    value_flags: frozenset[str],
) -> int | None:
    """Advance past option tokens until the first execution target.

    Returns the index of ``-m``/``--module`` or a file operand. Returns
    ``None`` when ``-c``, ``--``, a lone ``-``, or a truncated flag value
    would become the executed program.
    """
    while index < len(argv):
        token = argv[index]
        if token in MODULE_TARGET_TOKENS:
            return index
        if token in FORBIDDEN_EXECUTION_TOKENS:
            return None
        if not token.startswith("-"):
            return index
        name, has_inline_value, _remainder = token.partition("=")
        if name in value_flags and not has_inline_value:
            if index + 1 >= len(argv):
                return None
            index += 2
            continue
        index += 1
    return None


def _coverage_run_invokes_pytest(argv: Sequence[str], start: int) -> bool:
    """Return whether ``coverage run`` (or ``python -m coverage run``) runs pytest.

    Coverage flags may appear before the module pair. A script path, ``-c``,
    ``--``, or a prior ``-m``/``--module`` whose value is not ``pytest`` is
    rejected so ``coverage run attacker.py -m pytest`` cannot execute.
    """
    if start >= len(argv) or argv[start] != "run":
        return False
    index = _skip_flag_tokens(
        argv,
        start + 1,
        value_flags=COVERAGE_RUN_FLAG_TAKES_VALUE,
    )
    if index is None or index + 1 >= len(argv):
        return False
    if argv[index] not in MODULE_TARGET_TOKENS:
        return False
    return argv[index + 1] == "pytest"


def _python_invokes_pytest(argv: Sequence[str]) -> bool:
    """Return whether a Python interpreter's first module target is pytest.

    Interpreter flags may precede ``-m``. The first ``-m`` must be ``pytest``,
    or ``coverage`` followed by a ``run`` that itself invokes pytest. File
    targets such as ``python attacker.py -m pytest`` are rejected.
    """
    index = _skip_flag_tokens(argv, 1, value_flags=PYTHON_FLAG_TAKES_VALUE)
    if index is None or index + 1 >= len(argv) or argv[index] != "-m":
        return False
    module = argv[index + 1]
    if module == "pytest":
        return True
    if module == "coverage":
        return _coverage_run_invokes_pytest(argv, index + 2)
    return False


def _is_pytest_argv(argv: Sequence[str]) -> bool:
    """Return whether argv is a supported direct pytest invocation.

    Allowed runners are ``pytest``, ``python[3]`` whose first ``-m`` target is
    pytest (or ``coverage run ... -m pytest``), and ``coverage run`` whose
    first module target is pytest. Flags may precede that first module pair.
    A later ``-m pytest`` after a file, ``-c``, or another module cannot make
    an attacker program look like pytest.
    """
    if not argv:
        return False
    executable = _basename(argv[0])
    if executable in PYTEST_EXECUTABLES:
        return True
    if executable in PYTHON_EXECUTABLES or PYTHON_VERSIONED_RE.fullmatch(executable):
        return _python_invokes_pytest(argv)
    if executable == "coverage":
        return _coverage_run_invokes_pytest(argv, 1)
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


def _iter_run_command_lines(text: str) -> list[str]:
    """Yield every individual command-line candidate from each ``run:`` step.

    A single-line ``run: <command>`` step yields that one candidate. A
    block-scalar ``run: |``/``run: >`` step yields every non-blank line
    indented more than the ``run:`` key, one candidate per line -- the block
    is never accepted or rejected as a unit. Each candidate still goes
    through the unchanged :func:`parse_safe_pytest_command` gate, so a line
    that is not itself a recognized pytest invocation (for example a
    ``coverage report`` or ``interrogate`` line in the same block) is simply
    never collected, never executed, and never given any special treatment.
    A command that only becomes a real invocation after YAML folded-scalar
    (``>``) line joining is not reassembled here and so is not discovered --
    fail-closed on the ambiguous case rather than guess.
    """
    lines = text.splitlines()
    candidates: list[str] = []
    index = 0
    while index < len(lines):
        match = RUN_KEY_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        indent = len(match.group("indent"))
        rest = match.group("rest").strip()
        if BLOCK_SCALAR_HEADER_RE.match(rest):
            index += 1
            while index < len(lines):
                line = lines[index]
                if line.strip() == "":
                    index += 1
                    continue
                line_indent = len(line) - len(line.lstrip(" "))
                if line_indent <= indent:
                    break
                candidates.append(line.strip())
                index += 1
            continue
        if rest:
            candidates.append(rest)
        index += 1
    return candidates


def discover_commands(workflow_dir: pathlib.Path) -> list[list[str]]:
    """Return unique safe pytest argv from ci.yml/ci.yaml files.

    Scans both single-line and block-scalar ``run:`` steps (see
    :func:`_iter_run_command_lines`).
    """
    commands: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    if not workflow_dir.is_dir():
        return commands
    for path in sorted(workflow_dir.glob("ci.y*ml")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for candidate in _iter_run_command_lines(text):
            argv = parse_safe_pytest_command(candidate)
            key = tuple(argv or ())
            if not argv or key in seen:
                continue
            seen.add(key)
            commands.append(argv)
    return commands


def _project_python_path(project_dir: pathlib.Path) -> str:
    """Return the ``PYTHONPATH`` for a project, honoring a ``src`` package layout.

    Repositories that keep their importable package under ``src/`` (a
    ``src``-layout such as ``src/<package>``) cannot import it with the project
    root alone on the path, so an offline coverage run started from the project
    root fails at collection with ``ModuleNotFoundError``. When a ``src``
    directory exists it is prepended to the path so both ``src``-layout and
    flat-layout suites import correctly; otherwise the path is just the project
    root, preserving the previous behavior.
    """
    entries = ["."]
    if (project_dir / "src").is_dir():
        entries.insert(0, "src")
    return os.pathsep.join(entries)


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


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
