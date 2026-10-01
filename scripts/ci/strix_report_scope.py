#!/usr/bin/env python3
"""Require a completed PR scan report to identify its changed source scope."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# The PR scan target is a private directory holding only the changed files, so
# a path under it (as Strix reports it) is bound to this invocation's scope.
SCOPE_PATH_RE = re.compile(r"/workspace/strix-pr-scope\.[A-Za-z0-9]+/([A-Za-z0-9_./-]+)")


def _names_scoped_ancestor(report: str, changed_paths: list[str]) -> bool:
    """True when the report names a PR-scope directory or file containing a changed path."""
    for match in SCOPE_PATH_RE.finditer(report):
        named = match.group(1).strip("/")
        if named and any(path == named or path.startswith(named + "/") for path in changed_paths):
            return True
    return False


def validate(output: Path, changed_paths: list[str]) -> None:
    """Validate that a completed Strix report covers changed source scope."""

    if not output.is_dir() or output.is_symlink():
        raise ValueError("scan output directory is missing")
    runs = [path for path in output.iterdir() if path.is_dir() and not path.is_symlink()]
    if len(runs) != 1:
        raise ValueError("expected exactly one current scan report")
    run = runs[0]
    metadata_path = run / "run.json"
    report_path = run / "penetration_test_report.md"
    if any(path.is_symlink() or not path.is_file() for path in (metadata_path, report_path)):
        raise ValueError("scan report files are missing or linked")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(metadata, dict):
        raise ValueError("scan metadata is not an object")
    results = metadata.get("scan_results") or {}
    if not isinstance(results, dict):
        raise ValueError("scan results are not an object")
    if metadata.get("status") != "completed" or results.get("scan_completed") is not True or results.get("success") is not True:
        raise ValueError("scan report is incomplete")
    report = report_path.read_text(encoding="utf-8")
    if not any(path in report for path in changed_paths) and not _names_scoped_ancestor(report, changed_paths):
        raise ValueError("scan report does not identify a changed source file")


if __name__ == "__main__":
    try:
        validate(Path(sys.argv[1]), sys.argv[2:])
    except (IndexError, OSError, ValueError, TypeError) as error:
        print(f"ERROR: Strix report scope: {error}", file=sys.stderr)
        raise SystemExit(1) from error
