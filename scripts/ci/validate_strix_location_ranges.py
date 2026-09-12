"""Validate Strix finding locations against a trusted scan tree."""

from __future__ import annotations

import sys
from pathlib import Path


def location_state(repo_root: Path, scan_target: Path | None, records_path: Path) -> int:
    """Return 0 for all invalid, 1 for mixed, 2 for all valid, 3 for unnumbered."""
    numbered = 0
    invalid = 0
    records = records_path.read_text(encoding="utf-8", errors="replace").splitlines()
    for record in records:
        parts = record.split("\t")
        if len(parts) != 3 or not parts[1].strip():
            continue
        numbered += 1
        path, start_raw, end_raw = (part.strip() for part in parts)
        try:
            start, end = int(start_raw), int(end_raw)
        except ValueError:
            invalid += 1
            continue
        candidates = ([scan_target / path] if scan_target is not None else [])
        candidates.append(repo_root / path)
        source = next(
            (
                candidate
                for candidate in candidates
                if candidate.is_file() and not candidate.is_symlink()
            ),
            None,
        )
        if source is None or start < 1 or end < start:
            invalid += 1
            continue
        try:
            with source.open("r", encoding="utf-8", errors="replace") as source_file:
                line_count = sum(1 for _ in source_file)
        except OSError:
            invalid += 1
            continue
        if end > line_count:
            invalid += 1

    if numbered and invalid == numbered:
        return 0
    if numbered and invalid == 0:
        return 2
    if numbered:
        return 1
    return 3


def main(argv: list[str] | None = None) -> int:
    """Validate ``repo_root scan_target records_file`` from the command line."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        raise SystemExit("usage: validate_strix_location_ranges.py REPO_ROOT SCAN_TARGET RECORDS")
    scan_target = Path(args[1]) if args[1] else None
    return location_state(Path(args[0]), scan_target, Path(args[2]))


if __name__ == "__main__":
    raise SystemExit(main())
