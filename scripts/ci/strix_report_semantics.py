#!/usr/bin/env python3
"""Safely import Strix reports and classify contradictory no-finding records."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

MAX_REPORT_FILE_BYTES = 8 * 1024 * 1024
MAX_ATTEMPT_BYTES = 64 * 1024 * 1024
GIT_SHA = re.compile(r"^[0-9a-fA-F]{40}$")
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
    re.compile(r"\bno\s+exploitable\s+(?:security\s+)?issues?\b", re.IGNORECASE),
)
POSITIVE_FINDING_PATTERNS = (
    re.compile(r"\bproof\s+of\s+concept\b", re.IGNORECASE),
    re.compile(r"\breproduction\s+steps?\b", re.IGNORECASE),
    re.compile(r"\b(?:successfully\s+)?exploited\b", re.IGNORECASE),
    re.compile(r"\bconfirmed\s+(?:authentication\s+)?bypass\b", re.IGNORECASE),
    re.compile(r"\bexploit(?:ation)?\s+path\b", re.IGNORECASE),
    re.compile(
        r"\b(?:attacker|unauthenticated\s+user)\s+"
        r"(?:can|could|is\s+able\s+to)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\ballows?\s+(?:an?\s+)?(?:attacker|unauthenticated\s+user)\b",
        re.IGNORECASE,
    ),
)


def _regular_file(path: Path) -> Path:
    """Resolve a bounded regular report file without accepting symlinks."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"report must be a regular non-symlink file: {path}")
    if path.stat().st_size > MAX_REPORT_FILE_BYTES:
        raise ValueError(f"report exceeds size limit: {path}")
    return path.resolve(strict=True)


def _independent_no_finding_spans(text: str) -> list[tuple[int, int]]:
    """Return non-overlapping evidence spans so one sentence counts only once."""
    spans = sorted(
        (match.start(), match.end())
        for pattern in NO_FINDING_PATTERNS
        for match in pattern.finditer(text)
    )
    independent: list[tuple[int, int]] = []
    for start, end in spans:
        if independent and start < independent[-1][1]:
            previous_start, previous_end = independent[-1]
            independent[-1] = (previous_start, max(previous_end, end))
        else:
            independent.append((start, end))
    return independent


def is_self_negating_report(path: Path) -> bool:
    """Return true only for strongly contradictory no-finding pseudo-records."""
    resolved = _regular_file(path)
    text = resolved.read_text(encoding="utf-8", errors="replace")
    no_finding_evidence = _independent_no_finding_spans(text)
    positive_evidence = any(pattern.search(text) for pattern in POSITIVE_FINDING_PATTERNS)
    return len(no_finding_evidence) >= 2 and not positive_evidence


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


def _validate_scope_sha(value: str, label: str) -> str | None:
    """Validate an optional exact PR scope commit SHA."""
    normalized = value.strip()
    if not normalized:
        return None
    if not GIT_SHA.fullmatch(normalized):
        raise ValueError(f"{label} must be an exact 40-character git SHA")
    return normalized.lower()


def _write_evidence_receipt(
    destination: Path,
    selected: list[Path],
    source: Path,
    started_at_epoch: int,
    base_sha: str,
    head_sha: str,
) -> None:
    """Bind imported report hashes to the exact PR base/head evidence scope."""
    normalized_base = _validate_scope_sha(base_sha, "base_sha")
    normalized_head = _validate_scope_sha(head_sha, "head_sha")
    if bool(normalized_base) != bool(normalized_head):
        raise ValueError("base_sha and head_sha must be supplied together")
    file_records = [
        {
            "path": source_file.relative_to(source).as_posix(),
            "sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
            "size_bytes": source_file.stat().st_size,
        }
        for source_file in sorted(selected)
    ]
    receipt = {
        "schema_version": 1,
        "evidence_kind": "current_attempt_strix_report_import",
        "started_at_epoch": started_at_epoch,
        "pr_base_sha": normalized_base,
        "pr_head_sha": normalized_head,
        "files": file_records,
    }
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
    receipt_digest = hashlib.sha256(encoded).hexdigest()
    receipt_directory = destination / "gate-evidence"
    if receipt_directory.is_symlink():
        raise ValueError("gate evidence directory must not be a symlink")
    receipt_directory.mkdir(parents=True, exist_ok=True)
    receipt_path = receipt_directory / f"{started_at_epoch}-{receipt_digest[:16]}.json"
    if receipt_path.exists():
        if receipt_path.is_symlink() or receipt_path.read_bytes() != encoded:
            raise ValueError("conflicting Strix gate evidence receipt")
        return
    receipt_path.write_bytes(encoded)
    receipt_path.chmod(0o600)


def import_current_attempt_reports(
    source_root: Path,
    destination_root: Path,
    started_at_epoch: int,
    base_sha: str = "",
    head_sha: str = "",
) -> int:
    """Copy current-attempt regular files and bind them to the PR evidence scope."""
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
    if selected:
        _write_evidence_receipt(
            destination,
            selected,
            source,
            started_at_epoch,
            base_sha,
            head_sha,
        )
    return copied


def main(argv: list[str]) -> int:
    """Expose narrow shell-safe commands for the Strix gate."""
    try:
        if len(argv) == 3 and argv[1] == "is-self-negating":
            return 0 if is_self_negating_report(Path(argv[2])) else 1
        if len(argv) == 7 and argv[1] == "import-current-attempt":
            copied = import_current_attempt_reports(
                Path(argv[2]),
                Path(argv[3]),
                int(argv[4]),
                argv[5],
                argv[6],
            )
            print(copied)
            return 0
    except (OSError, ValueError, UnicodeError) as exc:
        print(f"Strix report semantics validation failed: {exc}", file=sys.stderr)
        return 2
    print(
        f"usage: {argv[0]} is-self-negating <report> | "
        "import-current-attempt <source> <destination> <started-at-epoch> "
        "<base-sha> <head-sha>",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
