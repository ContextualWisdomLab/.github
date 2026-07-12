"""Deterministic syntax/parse gate for the files changed in a pull request.

The OpenCode reviewer reads diffs and the coverage-evidence job runs the
repository test suites, so a syntax error in a changed file that no test
imports -- or in a language with no wired-in test runner -- can slip through
and be approved. This gate parses each changed file with a cheap, reliable,
per-file check and fails when any changed file does not parse, which blocks
approval through the coverage-evidence gate.

The gate is deliberately conservative: it only checks languages whose per-file
syntax is unambiguous (so it never fails valid code), and it *skips* -- never
fails -- a file whose required tool is unavailable, was deleted, or has an
unrecognized extension. A ``failed`` result therefore always means a genuine
syntax error in a current changed file.
"""

from __future__ import annotations

import argparse
import ast
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

OK = "ok"
FAILED = "failed"
SKIPPED = "skipped"

DETAIL_LIMIT = 400


def check_python(path: Path) -> tuple[str, str]:
    """Return the parse result for a Python source file using ``ast.parse``."""
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return (FAILED, f"{exc.msg} (line {exc.lineno})")
    return (OK, "")


def check_with_command(tool: str, command: Sequence[str], path: Path) -> tuple[str, str]:
    """Return a per-file parse result from an external ``tool`` syntax command.

    The check is skipped (never failed) when ``tool`` is not on PATH so a
    runner without that toolchain cannot block a PR with a false positive.
    """
    if shutil.which(tool) is None:
        return (SKIPPED, f"{tool} is not available on this runner")
    completed = subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr.strip() or completed.stdout.strip() or "")[:DETAIL_LIMIT]
        return (FAILED, detail or f"{tool} reported a syntax error")
    return (OK, "")


def check_shell(path: Path) -> tuple[str, str]:
    """Return the parse result for a shell script using ``bash -n``."""
    return check_with_command("bash", ["bash", "-n", str(path)], path)


def check_javascript(path: Path) -> tuple[str, str]:
    """Return the parse result for a JavaScript file using ``node --check``."""
    return check_with_command("node", ["node", "--check", str(path)], path)


# Only extensions whose per-file syntax is unambiguous are checked. Dialect-
# ambiguous formats (JSON with comments/trailing commas, multi-document YAML,
# TSX/JSX, project-context languages like Rust/Go) are intentionally omitted to
# guarantee zero false positives.
EXTENSION_CHECKERS = {
    ".py": check_python,
    ".sh": check_shell,
    ".bash": check_shell,
    ".js": check_javascript,
    ".cjs": check_javascript,
    ".mjs": check_javascript,
}


def check_changed_file(path: Path) -> tuple[str, str]:
    """Return the syntax result for one changed file path."""
    if not path.is_file():
        return (SKIPPED, "path is not a current regular file")
    checker = EXTENSION_CHECKERS.get(path.suffix.lower())
    if checker is None:
        return (SKIPPED, "no unambiguous per-file syntax check for this extension")
    return checker(path)


def read_changed_files(changed_files_file: Path) -> list[str]:
    """Return the newline-delimited changed file paths, ignoring blank lines."""
    text = changed_files_file.read_text(encoding="utf-8", errors="replace")
    return [line.strip() for line in text.splitlines() if line.strip()]


def run_gate(changed_files: Sequence[str]) -> tuple[list[tuple[str, str]], int, int]:
    """Return ``(failures, checked_count, skipped_count)`` for the changed files.

    ``failures`` is a list of ``(path, detail)`` for files with a syntax error.
    """
    failures: list[tuple[str, str]] = []
    checked = 0
    skipped = 0
    for raw_path in changed_files:
        result, detail = check_changed_file(Path(raw_path))
        if result == SKIPPED:
            skipped += 1
            continue
        checked += 1
        if result == FAILED:
            failures.append((raw_path, detail))
    return failures, checked, skipped


def format_report(failures: Sequence[tuple[str, str]], checked: int, skipped: int) -> str:
    """Return a human-readable gate report for logs and evidence."""
    lines = [
        f"Changed-file syntax gate: {checked} checked, {skipped} skipped, {len(failures)} failed."
    ]
    for path, detail in failures:
        lines.append(f"- SYNTAX ERROR {path}: {detail}")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--changed-files-file", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the syntax gate and return a non-zero exit code on any syntax error."""
    args = parse_args(argv)
    changed_files = read_changed_files(args.changed_files_file)
    failures, checked, skipped = run_gate(changed_files)
    print(format_report(failures, checked, skipped))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
