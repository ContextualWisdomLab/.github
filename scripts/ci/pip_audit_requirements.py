"""Audit Python requirement files without re-resolving hashed override locks.

pip-audit 2.10's default path invokes pip to resolve each ``requirements*.txt``
file. That lies about a complete hashed lock compiled with a documented
override: pip reports ``ResolutionImpossible`` (strix-agent ``cryptography<49``
versus the CVE-fixed ``cryptography==50.0.0`` pin) and the workflow labels the
failure ``known-vulnerable``. This helper audits validated hashed locks with
``--disable-pip`` so the pinned set is checked against the advisory database
without re-applying stale metadata bounds.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence


Runner = Callable[[Sequence[str]], int]
SKIP_DISCOVERY_PARTS = frozenset(
    {".git", ".venv", "venv", "node_modules", "__pycache__"}
)
_HASH_FIELD = re.compile(r"--hash=sha256:[0-9a-f]{64}")


class AuditConfigurationError(RuntimeError):
    """Signal that repository-controlled audit input is unsafe or ambiguous."""


def _require_regular_file(path: pathlib.Path) -> None:
    """Require one existing regular file without following a symbolic link."""

    try:
        metadata = path.lstat()
    except OSError:
        raise AuditConfigurationError(
            "requirements input could not be inspected safely"
        ) from None
    if not stat.S_ISREG(metadata.st_mode):
        raise AuditConfigurationError(
            "requirements input must be a regular non-symlink file"
        )


def _requirement_lines(path: pathlib.Path) -> list[str]:
    """Return strict UTF-8 logical lines, joining backslash continuations."""

    _require_regular_file(path)
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeError:
        raise AuditConfigurationError("invalid UTF-8 requirements input") from None
    joined = text.replace("\r\n", "\n").replace("\\\n", " ")
    lines: list[str] = []
    for raw_line in joined.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _is_exact_hashed_requirement(line: str) -> bool:
    """Return whether one line is an exact ``==`` pin plus SHA-256 hashes."""

    fields = re.split(r"\s+(?=--hash=)", line)
    requirement = fields[0].strip()
    hash_fields = fields[1:]
    if not requirement or requirement.startswith("-") or "==" not in requirement:
        return False
    return bool(hash_fields) and all(
        _HASH_FIELD.fullmatch(field) is not None for field in hash_fields
    )


def is_override_file(path: pathlib.Path) -> bool:
    """Return whether *path* is a compile-time override input, not an install set."""

    return path.name.endswith("-overrides.txt")


def is_hashed_lock(path: pathlib.Path) -> bool:
    """Return whether *path* is a complete, syntactically bounded hashed lock.

    A ``*-hashes.txt`` name, a lone ``--require-hashes`` directive, a pip
    option carrying hash-shaped text, or a mixed hashed-plus-unhashed file is
    not sufficient. Every substantive package line must be an exact ``==`` pin
    carrying one or more complete SHA-256 hashes before ``--disable-pip`` is
    allowed to bypass pip's resolver.
    """

    lines = _requirement_lines(path)
    package_lines = [line for line in lines if line != "--require-hashes"]
    return bool(package_lines) and all(
        _is_exact_hashed_requirement(line) for line in package_lines
    )


def _is_regular_non_symlink(path: pathlib.Path) -> bool:
    """Return whether an existing path is a regular file without following it."""

    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except OSError:
        return False


def hashed_sibling(path: pathlib.Path) -> pathlib.Path | None:
    """Return a valid compiled ``*-hashes.txt`` sibling for one source input."""

    if is_hashed_lock(path) or is_override_file(path):
        return None
    if not path.name.endswith(".txt"):
        return None
    sibling = path.with_name(f"{path.name[:-4]}-hashes.txt")
    if not _is_regular_non_symlink(sibling):
        return None
    if not is_hashed_lock(sibling):
        return None
    return sibling


def audit_command(path: pathlib.Path) -> list[str] | None:
    """Return the pip-audit argv for *path*, or ``None`` to skip the file.

    Validated hashed locks are audited with ``--disable-pip`` so pip cannot
    re-apply a stale ``Requires-Dist`` upper bound. Compile-time override files
    and unhashed inputs with a validated hashed sibling are skipped because the
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
    """Return regular requirement files while rejecting matching symlinks."""

    found: list[pathlib.Path] = []
    for path in sorted(root.rglob("requirements*.txt")):
        try:
            relative_parts = path.relative_to(root).parts
        except ValueError:
            raise AuditConfigurationError(
                "requirements input escaped the audit root"
            ) from None
        if SKIP_DISCOVERY_PARTS.intersection(relative_parts):
            continue
        try:
            metadata = path.lstat()
        except OSError:
            raise AuditConfigurationError(
                "requirements input could not be inspected safely"
            ) from None
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise AuditConfigurationError(
                "requirements input must be a regular non-symlink file"
            )
        found.append(path)
    return found


def should_audit_project_manifest(root: pathlib.Path) -> bool:
    """Return whether a PEP 621 or pylock manifest exists within two levels."""

    for current in (root, *list(root.glob("*"))):
        try:
            current_metadata = current.lstat()
        except OSError:
            continue
        if not stat.S_ISDIR(current_metadata.st_mode):
            continue
        pyproject = current / "pyproject.toml"
        if _is_regular_non_symlink(pyproject):
            return True
        for candidate in current.glob("pylock.*.toml"):
            if _is_regular_non_symlink(candidate):
                return True
    return False


def _display_path(root: pathlib.Path, path: pathlib.Path) -> str:
    """Return an ASCII JSON string safe for GitHub Actions log output."""

    try:
        relative = path.relative_to(root).as_posix()
    except ValueError:
        relative = path.name
    return json.dumps(relative, ensure_ascii=True)


def run_audits(
    root: pathlib.Path,
    *,
    runner: Runner | None = None,
) -> int:
    """Audit discovered inputs, returning 2 for unsafe repository metadata."""

    execute: Runner = runner or (
        lambda command: subprocess.run(command, check=False).returncode
    )
    status = 0
    try:
        requirement_files = discover_requirement_files(root)
        for path in requirement_files:
            command = audit_command(path)
            display_path = _display_path(root, path)
            if command is None:
                print(
                    f"skip {display_path} (validated hashed lock is audited)",
                    flush=True,
                )
                continue
            print(f"::group::pip-audit {display_path}", flush=True)
            if execute(command) != 0:
                status = 1
            print("::endgroup::", flush=True)
        if should_audit_project_manifest(root):
            command = ["pip-audit", "--strict", "--desc=on", "."]
            print("::group::pip-audit . (project manifest)", flush=True)
            if execute(command) != 0:
                status = 1
            print("::endgroup::", flush=True)
    except AuditConfigurationError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 2
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
        print("::error::audit root is not a directory", file=sys.stderr)
        return 2
    return run_audits(root)


if __name__ == "__main__":
    raise SystemExit(main())
