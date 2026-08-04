"""Install trusted base-commit Python hash locks without package overlays.

Each candidate is preflighted independently, incomplete supplements may be
recovered only with sibling locks, and accepted closures are installed in one
pip transaction. The single transaction prevents repeated installs from
leaving packages such as NumPy partially overlaid in the coverage image.
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
        r"In --require-hashes mode, all requirements must have their versions pinned with ==",
        re.IGNORECASE,
    ),
    re.compile(
        r"Hashes are required in --require-hashes mode, but they are missing from some requirements",
        re.IGNORECASE,
    ),
    re.compile(r"requires a different Python", re.IGNORECASE),
)
FATAL_PREFLIGHT_FAILURES = (
    re.compile(
        r"THESE PACKAGES DO NOT MATCH THE HASHES FROM THE REQUIREMENTS FILE",
        re.IGNORECASE,
    ),
    re.compile(r"WARNING:\s*Retrying\b", re.IGNORECASE),
    re.compile(r"Could not fetch URL", re.IGNORECASE),
)
DEFERABLE_ERROR_LINES = (
    re.compile(
        r"^ERROR:\s*In --require-hashes mode, all requirements must have their versions pinned with ==",
        re.IGNORECASE,
    ),
    re.compile(
        r"^ERROR:\s*Hashes are required in --require-hashes mode, but they are missing from some requirements",
        re.IGNORECASE,
    ),
    re.compile(r"^ERROR:.*requires a different Python", re.IGNORECASE),
    re.compile(r"^ERROR:\s*Ignored the following yanked versions:", re.IGNORECASE),
    re.compile(
        r"^ERROR:\s*Ignored the following versions that require a different python version:",
        re.IGNORECASE,
    ),
)
UNSATISFIED_REQUIREMENT_RE = re.compile(
    r"^ERROR:\s*Could not find a version that satisfies the requirement "
    r"(?P<requirement>[^\s(]+)[^\n]*"
    r"\(from versions:\s*(?P<versions>[^)\n]*)\)",
    re.IGNORECASE | re.MULTILINE,
)
NO_MATCHING_DISTRIBUTION_RE = re.compile(
    r"^ERROR:\s*No matching distribution found for (?P<requirement>\S+)",
    re.IGNORECASE | re.MULTILINE,
)
CONCRETE_VERSION_RE = re.compile(
    r"^(?:v)?(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*"
    r"(?:(?:a|b|rc)[0-9]+)?(?:(?:\.post|-)[0-9]+)?"
    r"(?:\.dev[0-9]+)?(?:\+[a-z0-9]+(?:[._-][a-z0-9]+)*)?$",
    re.IGNORECASE,
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


def _manifest_entries(requirements_root: pathlib.Path) -> list[LockCandidate]:
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
        entries.append(LockCandidate(generated_file, str(source_path), candidate))
    return entries


def _pip_command(requirements: Sequence[pathlib.Path], *, preflight: bool) -> list[str]:
    """Build one hash-enforced pip command for the supplied lock closure."""

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
    """Keep dependency root causes visible without flooding Actions logs."""

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


def _normalized_requirement_token(requirement: str) -> str:
    """Normalize harmless diagnostic punctuation for exact token comparison."""

    return requirement.rstrip(".,").casefold()


def _is_concrete_version_list(version_list: str) -> bool:
    """Return whether every comma-separated token is a concrete PEP 440 version."""

    tokens = [token.strip() for token in version_list.split(",")]
    return bool(tokens) and all(
        bool(token) and CONCRETE_VERSION_RE.fullmatch(token) is not None
        for token in tokens
    )


def _matching_binary_unavailability_requirements(output: str) -> set[str]:
    """Return exact pins paired across pip binary-unavailability diagnostics."""

    unsatisfied = {
        _normalized_requirement_token(match.group("requirement"))
        for match in UNSATISFIED_REQUIREMENT_RE.finditer(output)
        if _is_concrete_version_list(match.group("versions"))
    }
    unmatched = {
        _normalized_requirement_token(match.group("requirement"))
        for match in NO_MATCHING_DISTRIBUTION_RE.finditer(output)
    }
    return unsatisfied if unsatisfied and unsatisfied == unmatched else set()


def _contains_unclassified_error(output: str) -> bool:
    """Return whether pip emitted an error outside the deferable contract."""

    matching_requirements = _matching_binary_unavailability_requirements(output)
    for line in output.splitlines():
        normalized_line = line.strip()
        if not normalized_line.casefold().startswith("error:"):
            continue
        unsatisfied_match = UNSATISFIED_REQUIREMENT_RE.search(normalized_line)
        if unsatisfied_match is not None:
            requirement = _normalized_requirement_token(
                unsatisfied_match.group("requirement")
            )
            if requirement in matching_requirements and _is_concrete_version_list(
                unsatisfied_match.group("versions")
            ):
                continue
            return True
        unmatched_distribution = NO_MATCHING_DISTRIBUTION_RE.search(normalized_line)
        if unmatched_distribution is not None:
            requirement = _normalized_requirement_token(
                unmatched_distribution.group("requirement")
            )
            if requirement in matching_requirements:
                continue
            return True
        if any(pattern.search(normalized_line) for pattern in DEFERABLE_ERROR_LINES):
            continue
        return True
    return False


def _is_deferable_preflight_failure(output: str) -> bool:
    """Return whether a failed candidate may be grouped or safely skipped."""

    normalized_output = output.strip()
    return (
        bool(normalized_output)
        and not any(
            pattern.search(normalized_output) for pattern in FATAL_PREFLIGHT_FAILURES
        )
        and not _contains_unclassified_error(normalized_output)
        and (
            any(
                pattern.search(normalized_output)
                for pattern in DEFERABLE_PREFLIGHT_FAILURES
            )
            or bool(_matching_binary_unavailability_requirements(normalized_output))
        )
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
        f"{entry_label}; only incomplete hash closures, explicit Python "
        "interpreter incompatibility, or paired same-requirement binary "
        "unavailability with concrete version evidence may be deferred.",
        file=stderr,
    )
    failure_output = _bounded_failure_output(output)
    if failure_output:
        print(failure_output, file=stderr)


def _preflight(
    requirements: Sequence[pathlib.Path], runner: Runner
) -> subprocess.CompletedProcess[str]:
    """Run one resolver-only hash validation."""

    return runner(
        _pip_command(requirements, preflight=True),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def install_materialized_locks(
    requirements_root: pathlib.Path,
    *,
    runner: Runner = subprocess.run,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Preflight accepted locks and install them in one pip transaction."""

    try:
        entries = _manifest_entries(requirements_root)
    except (OSError, ValueError) as exc:
        print(f"::error::Could not validate base Python locks: {exc}", file=stderr)
        return 2

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
        preflight = _preflight([entry.path], runner)
        preflight_results[entry.generated_file] = preflight
        if preflight.returncode == 0:
            independently_valid.add(entry.generated_file)
        elif not _is_deferable_preflight_failure(preflight.stdout or ""):
            _report_fatal_preflight_failure(
                entry.source, preflight.stdout or "", stderr=stderr
            )
            return preflight.returncode or 1

    by_source_directory: dict[str, list[LockCandidate]] = defaultdict(list)
    for entry in entries:
        by_source_directory[entry.source_directory].append(entry)

    accepted: list[LockCandidate] = []
    covered_files: set[str] = set()
    accepted_plan_count = 0
    for source_directory, directory_entries in by_source_directory.items():
        invalid_entries = [
            entry
            for entry in directory_entries
            if entry.generated_file not in independently_valid
        ]
        if not invalid_entries or len(directory_entries) < 2:
            continue
        print(
            "Preflighting same-directory trusted base Python lock group "
            f"{source_directory or '.'}: "
            + ", ".join(entry.source for entry in directory_entries),
            file=stdout,
            flush=True,
        )
        group_preflight = _preflight(
            [entry.path for entry in directory_entries], runner
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
        accepted.extend(directory_entries)
        covered_files.update(entry.generated_file for entry in directory_entries)
        accepted_plan_count += 1
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
            accepted.append(entry)
            covered_files.add(entry.generated_file)
            accepted_plan_count += 1
            continue
        skipped += 1
        print(
            "::warning::Skipping trusted base Python requirement candidate "
            f"{entry.source}: it is not an independently complete dependency "
            "closure for the coverage interpreter and no same-directory lock "
            "group completed it.",
            file=stderr,
        )
        failure_output = _bounded_failure_output(
            preflight_results[entry.generated_file].stdout or ""
        )
        if failure_output:
            print(failure_output, file=stderr)

    unique_accepted: list[LockCandidate] = []
    seen_accepted: set[str] = set()
    for entry in accepted:
        if entry.generated_file not in seen_accepted:
            seen_accepted.add(entry.generated_file)
            unique_accepted.append(entry)

    if unique_accepted:
        accepted_paths = [entry.path for entry in unique_accepted]
        accepted_sources = ", ".join(entry.source for entry in unique_accepted)
        if accepted_plan_count > 1:
            print(
                "Preflighting aggregate trusted base Python lock closure: "
                f"{accepted_sources}.",
                file=stdout,
                flush=True,
            )
            aggregate_preflight = _preflight(accepted_paths, runner)
            if aggregate_preflight.returncode != 0:
                _report_fatal_preflight_failure(
                    accepted_sources,
                    aggregate_preflight.stdout or "",
                    stderr=stderr,
                )
                return aggregate_preflight.returncode or 1
        print(
            "Installing aggregate trusted base Python lock closure in one "
            f"transaction: {accepted_sources}.",
            file=stdout,
            flush=True,
        )
        installation = runner(
            _pip_command(accepted_paths, preflight=False),
            check=False,
        )
        if installation.returncode != 0:
            print(
                "::error::The aggregate preflight-valid trusted base Python "
                f"lock closure failed during installation: {accepted_sources}.",
                file=stderr,
            )
            return installation.returncode or 1

    print(
        "Trusted base Python lock installation summary: "
        f"candidates={len(entries)} installed={len(unique_accepted)} skipped={skipped}.",
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
