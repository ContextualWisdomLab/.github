"""Audit Python requirement files without re-resolving hashed override locks.

pip-audit 2.10's default path invokes pip to resolve each ``requirements*.txt``
file. That lies about a complete hashed lock compiled with a documented
override: pip reports ``ResolutionImpossible`` (strix-agent ``cryptography<49``
versus the CVE-fixed ``cryptography==50.0.0`` pin) and the workflow labels the
failure ``known-vulnerable``. This helper audits hashed locks with
``--disable-pip`` so the pinned set is checked against the advisory database
without re-applying stale metadata bounds.
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys
from collections.abc import Callable, Sequence


Runner = Callable[[Sequence[str]], int]
SKIP_DISCOVERY_PARTS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__"}
)


def _requirement_lines(path: pathlib.Path) -> list[str]:
    """Return logical requirement lines, joining backslash continuations."""

    text = path.read_text(encoding="utf-8", errors="ignore").replace("\r\n", "\n")
    joined = text.replace("\\\n", " ")
    lines: list[str] = []
    for raw_line in joined.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def is_override_file(path: pathlib.Path) -> bool:
    """Return whether *path* is a compile-time override input, not an install set."""

    return path.name.endswith("-overrides.txt")


def is_hashed_lock(path: pathlib.Path) -> bool:
    """Return whether *path* actually contains pip hash-checking evidence.

    A ``*-hashes.txt`` name, a lone ``--require-hashes`` directive, or a
    mixed file with one hashed line beside unhashed packages is not
    enough: those would otherwise be audited with ``--disable-pip`` and
    report a clean incomplete set.
    """

    lines = _requirement_lines(path)
    package_lines = [line for line in lines if line != "--require-hashes"]
    return bool(package_lines) and all("--hash=" in line for line in package_lines)


def hashed_sibling(path: pathlib.Path) -> pathlib.Path | None:
    """Return the compiled ``*-hashes.txt`` sibling when *path* is its input."""

    if is_hashed_lock(path) or is_override_file(path):
        return None
    if not path.name.endswith(".txt"):
        return None
    sibling = path.with_name(f"{path.name[:-4]}-hashes.txt")
    if sibling.is_file():
        return sibling
    return None


def audit_command(path: pathlib.Path) -> list[str] | None:
    """Return the pip-audit argv for *path*, or ``None`` to skip the file.

    Hashed locks are audited with ``--disable-pip`` so pip cannot re-apply a
    stale ``Requires-Dist`` upper bound. Compile-time override files and
    unhashed inputs that already have a hashed sibling are skipped because the
    lock is the install set a buyer actually receives.
    """

    if is_override_file(path):
        return None
    if is_hashed_lock(path):
        return [
            "pip-audit",
            "--strict",
            "--desc=on",
            "--disable-pip",
            "-r",
            str(path),
        ]
    if hashed_sibling(path) is not None:
        return None
    return ["pip-audit", "--strict", "--desc=on", "-r", str(path)]


def discover_requirement_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Return ``requirements*.txt`` files under *root*, skipping VCS and venvs."""

    found: list[pathlib.Path] = []
    for path in sorted(root.rglob("requirements*.txt")):
        if SKIP_DISCOVERY_PARTS.intersection(path.parts):
            continue
        if not path.is_file():
            continue
        found.append(path)
    return found


def should_audit_project_manifest(root: pathlib.Path) -> bool:
    """Return whether a PEP 621 or pylock manifest exists within two levels."""

    for current in (root, *list(root.glob("*"))):
        if not current.is_dir():
            continue
        if (current / "pyproject.toml").is_file():
            return True
        if any(current.glob("pylock.*.toml")):
            return True
    return False


def run_audits(
    root: pathlib.Path,
    *,
    runner: Runner | None = None,
) -> int:
    """Audit discovered requirement files and an optional project manifest."""

    execute: Runner = runner or (
        lambda command: subprocess.run(command, check=False).returncode
    )
    status = 0
    for path in discover_requirement_files(root):
        command = audit_command(path)
        if command is None:
            print(f"skip {path} (hashed lock is the audited install set)", flush=True)
            continue
        print(f"::group::pip-audit {' '.join(command[1:])}", flush=True)
        if execute(command) != 0:
            status = 1
        print("::endgroup::", flush=True)
    if should_audit_project_manifest(root):
        command = ["pip-audit", "--strict", "--desc=on", "."]
        print("::group::pip-audit . (project manifest)", flush=True)
        if execute(command) != 0:
            status = 1
        print("::endgroup::", flush=True)
    if status != 0:
        print(
            "::error::pip-audit reported known-vulnerable Python dependencies.",
            file=sys.stderr,
        )
    return status


def main(argv: list[str] | None = None) -> int:
    """CLI entry: audit requirement files under an optional root directory."""

    parser = argparse.ArgumentParser(
        description="Audit requirements without re-resolving hashed override locks."
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=pathlib.Path,
        default=pathlib.Path("."),
        help="Repository root to search (default: current directory)",
    )
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if not root.is_dir():
        print(f"::error::audit root is not a directory: {root}", file=sys.stderr)
        return 2
    return run_audits(root)


if __name__ == "__main__":
    raise SystemExit(main())
