#!/usr/bin/env python3
"""Safely import Strix reports and classify contradictory no-finding records."""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

MAX_REPORT_FILE_BYTES = 8 * 1024 * 1024
MAX_ATTEMPT_BYTES = 64 * 1024 * 1024
NO_FINDING_PATTERNS = (
    re.compile(
        r"^#{1,6}\s+no\b.{0,100}\bvulnerabilit(?:y|ies)\b.{0,40}"
        r"\b(?:found|discovered|identified)\b",
        re.IGNORECASE | re.MULTILINE,
    ),
    re.compile(
        r"\bno\s+(?:security\s+)?vulnerabilit(?:y|ies)\s+(?:were\s+)?"
        r"(?:found|discovered|identified)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bn/?a\s*[-:–—]\s*no\s+vulnerabilit(?:y|ies)\s+"
        r"(?:found|discovered|identified)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bno\s+immediate\s+remediation\s+is\s+required\b", re.IGNORECASE),
)
POSITIVE_FINDING_PATTERNS = (
    re.compile(r"\bproof\s+of\s+concept\b", re.IGNORECASE),
    re.compile(r"\baffected\s+(?:endpoint|file|component)\b", re.IGNORECASE),
    re.compile(
        r"(?m)^\s*(?:target|endpoint|location)\s*:\s*\S+", re.IGNORECASE
    ),
    re.compile(r"\breproduction\s+steps?\b", re.IGNORECASE),
    re.compile(r"\b(?:successfully\s+)?exploited\b", re.IGNORECASE),
    re.compile(r"\bconfirmed\s+(?:authentication\s+)?bypass\b", re.IGNORECASE),
)


def _regular_file(path: Path) -> Path:
    """Resolve a bounded regular report file without accepting symlinks."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"report must be a regular non-symlink file: {path}")
    if path.stat().st_size > MAX_REPORT_FILE_BYTES:
        raise ValueError(f"report exceeds size limit: {path}")
    return path.resolve(strict=True)


def is_self_negating_report(path: Path) -> bool:
    """Return true only for strongly contradictory no-finding pseudo-records."""
    resolved = _regular_file(path)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    no_finding_evidence = sum(
        bool(pattern.search(text)) for pattern in NO_FINDING_PATTERNS
    )
    positive_evidence = any(pattern.search(text) for pattern in POSITIVE_FINDING_PATTERNS)
    return no_finding_evidence >= 2 and not positive_evidence


def _assert_tree_is_regular(root: Path) -> list[Path]:
    """Return files below root while rejecting links and special filesystem nodes."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"report root must be a real directory: {root}")
    files: list[Path] = []
    for current, directory_names, file_names in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directory_names:
            candidate = current_path / name
            if candidate.is_symlink() or not candidate.is_dir():
                raise ValueError(f"unsafe report directory: {candidate}")
        for name in file_names:
            candidate = current_path / name
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError(f"unsafe report file: {candidate}")
            if candidate.stat().st_size > MAX_REPORT_FILE_BYTES:
                raise ValueError(f"report file exceeds size limit: {candidate}")
            files.append(candidate)
    return files


def import_current_attempt_reports(
    source_root: Path, destination_root: Path, started_at_epoch: int
) -> int:
    """Copy only current-attempt regular files into the trusted evaluation root."""
    if not source_root.exists():
        return 0
    source = source_root.resolve(strict=True)
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root.resolve(strict=True)
    if source == destination:
        return 0
    files = _assert_tree_is_regular(source)
    minimum_mtime = max(0, started_at_epoch - 2)
    selected = [path for path in files if int(path.stat().st_mtime) >= minimum_mtime]
    total_bytes = sum(path.stat().st_size for path in selected)
    if total_bytes > MAX_ATTEMPT_BYTES:
        raise ValueError("current Strix attempt reports exceed aggregate size limit")
    copied = 0
    for source_file in selected:
        relative = source_file.relative_to(source)
        destination_file = destination / relative
        destination_file.parent.mkdir(parents=True, exist_ok=True)
        if destination_file.exists():
            if destination_file.is_symlink() or not destination_file.is_file():
                raise ValueError(f"unsafe destination report path: {destination_file}")
            if destination_file.read_bytes() != source_file.read_bytes():
                raise ValueError(f"conflicting report copies: {relative}")
            continue
        shutil.copyfile(source_file, destination_file, follow_symlinks=False)
        destination_file.chmod(0o600)
        copied += 1
    return copied


def main(argv: list[str]) -> int:
    """Expose narrow shell-safe commands for the Strix gate."""
    try:
        if len(argv) == 3 and argv[1] == "is-self-negating":
            return 0 if is_self_negating_report(Path(argv[2])) else 1
        if len(argv) == 5 and argv[1] == "import-current-attempt":
            copied = import_current_attempt_reports(
                Path(argv[2]), Path(argv[3]), int(argv[4])
            )
            print(copied)
            return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"Strix report semantics validation failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"usage: {argv[0]} is-self-negating <report> | "
        "import-current-attempt <source> <destination> <started-at-epoch>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
