#!/usr/bin/env python3
"""Require a completed PR scan report to identify its changed source scope."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# The PR scan target is a private directory holding only the changed files, so
# a path under it (as Strix reports it) is bound to this invocation's scope.
# A sentence period ends a token only when a real delimiter (or end) follows it;
# "name.:suffix" or "name.@suffix" is a different file, not the changed path.
_TOKEN_DELIMITER = r"(?=$|[\s`\"'<>,;!?)])"
PATH_TOKEN_END = (
    r"(?=$|[\s`\"'<>,;!?)]"
    r"|:(?=[0-9]+(?::[0-9]+)?(?:$|[\s`\"'<>,;!?)]|\." + _TOKEN_DELIMITER + r"))"
    r"|\." + _TOKEN_DELIMITER + r")"
)
SCOPE_PATH_RE = re.compile(
    r"(?<![\w./-])/workspace/strix-pr-scope\.[A-Za-z0-9]+/([A-Za-z0-9_./-]+)"
    + PATH_TOKEN_END
)


def _names_scoped_ancestor(report: str, changed_paths: list[str]) -> bool:
    """True when the report names a PR-scope directory or file containing a changed path."""
    for match in SCOPE_PATH_RE.finditer(report):
        named = match.group(1).strip("/")
        if named and any(path == named or path.startswith(named + "/") for path in changed_paths):
            return True
    return False


def _token(text: str) -> re.Pattern[str]:
    """Match a path token only at whole-segment boundaries."""
    return re.compile(rf"(?<![\w./-]){re.escape(text)}/?" + PATH_TOKEN_END)


def _file_token(text: str) -> re.Pattern[str]:
    """Match a filename token without accepting suffixes or child paths."""
    return re.compile(rf"(?<![\w./-]){re.escape(text)}" + PATH_TOKEN_END)


def names_changed_path(report: str, path: str) -> bool:
    """Match exact file paths or a named directory plus its exact filename."""
    if _file_token(path).search(report) is not None:
        return True
    directory, _, name = path.rpartition("/")
    if not directory or _file_token(name).search(report) is None:
        return False
    if _token(directory).search(report) is not None:
        return True
    parts = directory.split("/")
    return any(
        _token("/".join(parts[:depth])).search(report)
        for depth in range(2, len(parts) + 1)
    )


def validate(output: Path, changed_paths: list[str]) -> None:
    """Raise ValueError unless one completed, unlinked report names changed scope."""

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
    if not any(names_changed_path(report, path) for path in changed_paths) and not _names_scoped_ancestor(report, changed_paths):
        raise ValueError("scan report does not identify a changed source file")


if __name__ == "__main__":
    try:
        validate(Path(sys.argv[1]), sys.argv[2:])
    except (IndexError, OSError, ValueError, TypeError) as error:
        print(f"ERROR: Strix report scope: {error}", file=sys.stderr)
        raise SystemExit(1) from error
