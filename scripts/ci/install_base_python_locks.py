"""Install independently complete base-commit Python hash locks.

The coverage image build may discover several hash-bearing requirements files
from a trusted base commit.  A file can hash every requirement it names while
still being only a supplement to another lock, so syntax alone cannot prove
that pip can install it as an independent dependency closure.  Preflight every
candidate with pip's hash enforcement, recover supplements only with sibling
locks from the same source directory, and skip candidates that still cannot
prove a complete closure.  Later coverage execution remains responsible for
proving that the resulting offline environment is sufficient for the target
repository.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TextIO


GENERATED_LOCK_RE = re.compile(r"^requirements-[0-9]{3}\.txt$")
DEFERABLE_PREFLIGHT_FAILURES = (
    re.compile(
        r"In --require-hashes mode, all requirements must have their versions "
        r"pinned with ==",
        re.IGNORECASE,
    ),
    re.compile(
        r"Hashes are required in --require-hashes mode, but they are missing "
        r"from some requirements",
        re.IGNORECASE,
    ),
    re.compile(r"requires a different Python", re.IGNORECASE),
)
Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class LockCandidate:
    """One materialized base requirements file and its trusted source path."""

    generated_file: str
    source: str
    path: pathlib.Path

    @property
    def source_directory(self) -> str:
        """Return the source directory used for supplement recovery groups."""
        parent = str(pathlib.PurePosixPath(self.source).parent)
        return "" if parent == "." else parent


def _manifest_entries(
    requirements_root: pathlib.Path,
) -> list[LockCandidate]:
    """Load and validate trusted materializer output."""
    root = requirements_root.resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise ValueError("base Python lock manifest must be a regular non-symlink file")
    try:
        manifest: Any = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"base Python lock manifest is invalid: {exc}") from exc
    if not isinstance(manifest, list):
        raise ValueError("base Python lock manifest must be a JSON array")

    entries: list[LockCandidate] = []
    seen_files: set[str] = set()
    for entry in manifest:
        if not isinstance(entry, dict):
            raise ValueError("base Python lock manifest entries must be objects")
        generated_file = entry.get("file")
        source = entry.get("source")
        if not isinstance(generated_file, str) or not GENERATED_LOCK_RE.fullmatch(
            generated_file
        ):
            raise ValueError("base Python lock manifest contains an unsafe file name")
        source_path = pathlib.PurePosixPath(source) if isinstance(source, str) else None
        if (
            source_path is None
            or source_path.is_absolute()
            or not source_path.parts
            or ".." in source_path.parts
        ):
            raise ValueError("base Python lock manifest contains an unsafe source path")
        if generated_file in seen_files:
            raise ValueError("base Python lock manifest contains duplicate file names")
        seen_files.add(generated_file)

        candidate = root / generated_file
        if not candidate.is_file() or candidate.is_symlink():
            raise ValueError(
                f"materialized base Python lock {generated_file} must be a regular file"
            )
        entries.append(
            LockCandidate(
                generated_file=generated_file,
                source=str(source_path),
                path=candidate,
            )
        )
    return entries


def _pip_command(requirements: Sequence[pathlib.Path], *, preflight: bool) -> list[str]:
    """Build a hash-enforced pip command for one candidate or recovery group."""
    command = [
        sys.executable,
        "-m",
        "pip",
        "install",
        "--break-system-packages",
        "--disable-pip-version-check",
        "--require-hashes",
        "--only-binary=:all:",
    ]
    if preflight:
        command.extend(["--dry-run", "--ignore-installed"])
    for requirements_file in requirements:
        command.extend(["-r", str(requirements_file)])
    return command


def _bounded_failure_output(output: str, *, maximum_lines: int = 120) -> str:
    """Keep the dependency root cause visible without flooding Actions logs."""
    lines = output.rstrip().splitlines()
    if len(lines) <= maximum_lines:
        return "\n".join(lines)
    leading_lines = 40
    trailing_lines = maximum_lines - leading_lines
    omitted = len(lines) - maximum_lines
    return "\n".join(
        [
            *lines[:leading_lines],
            f"... {omitted} dependency-resolution log lines omitted ...",
            *lines[-trailing_lines:],
        ]
    )


def _is_deferable_preflight_failure(output: str) -> bool:
    """Return whether a failed candidate may be grouped or safely skipped.

    A hash-bearing supplement can fail pip's independent-closure check because a
    transitive pin/hash lives in a sibling lock, and a base lock can explicitly
    reject the pinned coverage-image interpreter. Those states are safe to
    recover through a same-directory group or defer to the later networkless
    coverage run. Hash mismatches, resolver crashes, empty diagnostics, and
    registry/network failures remain fatal so a broken trusted build cannot be
    mistaken for an optional lock.
    """
    return bool(output.strip()) and any(
        pattern.search(output) for pattern in DEFERABLE_PREFLIGHT_FAILURES
    )


def _report_fatal_preflight_failure(
    entry_label: str,
    output: str,
    *,
    stderr: TextIO,
) -> None:
    """Publish one bounded, source-aware fatal preflight failure."""
    print(
        "::error::Trusted base Python lock preflight failed for "
        f"{entry_label}; only incomplete hash closures or explicit Python "
        "interpreter incompatibility may be deferred.",
        file=stderr,
    )
    failure_output = _bounded_failure_output(output)
    if failure_output:
        print(failure_output, file=stderr)


def install_materialized_locks(
    requirements_root: pathlib.Path,
    *,
    runner: Runner = subprocess.run,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Preflight and install independent base lock closures."""
    try:
        entries = _manifest_entries(requirements_root)
    except (OSError, ValueError) as exc:
        print(f"::error::Could not validate base Python locks: {exc}", file=stderr)
        return 2

    installed = 0
    skipped = 0
    preflight_results: dict[str, subprocess.CompletedProcess[str]] = {}
    independently_valid: set[str] = set()
    for entry in entries:
        print(
            f"Preflighting trusted base Python lock candidate {entry.source} "
            f"({entry.generated_file}).",
            file=stdout,
            flush=True,
        )
        preflight = runner(
            _pip_command([entry.path], preflight=True),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        preflight_results[entry.generated_file] = preflight
        if preflight.returncode == 0:
            independently_valid.add(entry.generated_file)
        elif not _is_deferable_preflight_failure(preflight.stdout or ""):
            _report_fatal_preflight_failure(
                entry.source,
                preflight.stdout or "",
                stderr=stderr,
            )
            return preflight.returncode or 1

    by_source_directory: dict[str, list[LockCandidate]] = defaultdict(list)
    for entry in entries:
        by_source_directory[entry.source_directory].append(entry)

    install_plans: list[list[LockCandidate]] = []
    covered_files: set[str] = set()
    for source_directory, directory_entries in by_source_directory.items():
        invalid_entries = [
            entry
            for entry in directory_entries
            if entry.generated_file not in independently_valid
        ]
        # ponytail: recover only one unambiguous two-file supplement pair;
        # multi-environment directories need an explicit include graph.
        if not invalid_entries or len(directory_entries) != 2:
            continue
        print(
            "Preflighting same-directory trusted base Python lock group "
            f"{source_directory or '.'}: "
            + ", ".join(entry.source for entry in directory_entries),
            file=stdout,
            flush=True,
        )
        group_preflight = runner(
            _pip_command([entry.path for entry in directory_entries], preflight=True),
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if group_preflight.returncode != 0:
            if not _is_deferable_preflight_failure(group_preflight.stdout or ""):
                _report_fatal_preflight_failure(
                    ", ".join(entry.source for entry in directory_entries),
                    group_preflight.stdout or "",
                    stderr=stderr,
                )
                return group_preflight.returncode or 1
            continue
        install_plans.append(directory_entries)
        covered_files.update(entry.generated_file for entry in directory_entries)
        print(
            "Recovered trusted base Python supplement(s) through a complete "
            f"same-directory hash closure: {source_directory or '.'}.",
            file=stdout,
            flush=True,
        )

    for entry in entries:
        if entry.generated_file in covered_files:
            continue
        if entry.generated_file in independently_valid:
            install_plans.append([entry])
            covered_files.add(entry.generated_file)
            continue

        skipped += 1
        print(
            "::warning::Skipping trusted base Python requirement candidate "
            f"{entry.source}: hash-bearing content is not an independently "
            "installable dependency closure and no same-directory lock group "
            "completed it.",
            file=stderr,
        )
        failure_output = _bounded_failure_output(
            preflight_results[entry.generated_file].stdout or ""
        )
        print(failure_output, file=stderr)

    for plan in install_plans:
        plan_sources = ", ".join(entry.source for entry in plan)
        print(
            f"Installing validated trusted base Python lock closure: {plan_sources}.",
            file=stdout,
            flush=True,
        )
        installation = runner(
            _pip_command([entry.path for entry in plan], preflight=False),
            check=False,
        )
        if installation.returncode != 0:
            print(
                "::error::A preflight-valid trusted base Python lock closure failed "
                f"during installation: {plan_sources}.",
                file=stderr,
            )
            return installation.returncode or 1
        installed += len(plan)

    print(
        "Trusted base Python lock installation summary: "
        f"candidates={len(entries)} installed={installed} skipped={skipped}.",
        file=stdout,
    )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Install materialized lock candidates supplied by the trusted workflow."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--requirements-root", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    return install_materialized_locks(args.requirements_root)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
