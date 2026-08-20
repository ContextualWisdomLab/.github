#!/usr/bin/env python3
"""Gate R coverage deferral on bounded testthat and peer-check evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence


MAX_LOG_BYTES = 2_000_000
PACKAGE_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9.]*\Z")
FAIL_SUMMARY_RE = re.compile(r"^\[\s*FAIL\s+(\d+)\s*\|", re.MULTILINE)
ERROR_BLOCK_RE = re.compile(r"^Error \(", re.MULTILINE)
PACKAGE_NOT_FOUND_CONDITION_RE = re.compile(
    r"^<packageNotFoundError/error/condition>$",
    re.MULTILINE,
)
MISSING_PACKAGE_RE = re.compile(r"there is no package called ['\"]([^'\"]+)['\"]")
DESCRIPTION_PACKAGE_SPEC_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9.]*)\s*(?:\([^()]*\))?\Z"
)
R_CMD_CHECK_RE = re.compile(r"\br[\s_-]*cmd[\s_-]*check\b", re.IGNORECASE)


def declared_suggests(description: str) -> set[str] | None:
    """Return validated package names from a DESCRIPTION ``Suggests`` field."""
    values: list[str] = []
    in_suggests = False
    found_suggests = False
    for line in description.splitlines():
        if line.startswith((" ", "\t")):
            if in_suggests:
                values.append(line.strip())
            continue
        field, separator, value = line.partition(":")
        if not separator:
            if in_suggests:
                return None
            continue
        in_suggests = field.casefold() == "suggests"
        if not in_suggests:
            continue
        if found_suggests:
            return None
        found_suggests = True
        values.append(value.strip())

    if not found_suggests:
        return set()
    raw_value = " ".join(values).strip()
    if not raw_value:
        return set()

    packages: set[str] = set()
    for raw_spec in raw_value.split(","):
        match = DESCRIPTION_PACKAGE_SPEC_RE.fullmatch(raw_spec.strip())
        if match is None:
            return None
        packages.add(match.group(1))
    return packages


def classify_testthat_failure(
    text: str,
    package: str,
    *,
    allowed_missing: set[str] | None = None,
) -> bool:
    """Return whether failures only miss the package or declared test dependencies."""
    if not PACKAGE_NAME_RE.fullmatch(package):
        return False
    allowed_packages = {package}
    if allowed_missing is not None:
        if any(not PACKAGE_NAME_RE.fullmatch(name) for name in allowed_missing):
            return False
        allowed_packages.update(allowed_missing)

    # ⚡ Bolt: Fast-path rejection before running expensive regex on potentially 2MB logs
    if "Error: Test failures" not in text:
        return False

    summaries = FAIL_SUMMARY_RE.findall(text)
    if not summaries:
        return False
    failure_count = int(summaries[-1])
    if failure_count <= 0:
        return False
    error_count = len(ERROR_BLOCK_RE.findall(text))
    condition_count = len(PACKAGE_NOT_FOUND_CONDITION_RE.findall(text))
    missing_packages = MISSING_PACKAGE_RE.findall(text)
    return (
        error_count == failure_count
        and condition_count == failure_count
        and len(missing_packages) == failure_count
        and all(name in allowed_packages for name in missing_packages)
    )


def has_successful_r_cmd_check(checks: Any) -> bool:
    """Return whether check JSON contains a successful R CMD check workflow."""
    if not isinstance(checks, list):
        return False
    for check in checks:
        if not isinstance(check, dict):
            continue
        if str(check.get("state") or "").upper() != "SUCCESS":
            continue
        label = f"{check.get('workflow') or ''} {check.get('name') or ''}"
        if R_CMD_CHECK_RE.search(label):
            return True
    return False


def _read_bounded_text(path: Path) -> str | None:
    """Read a regular bounded log, returning None for unsafe or unreadable input."""
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_LOG_BYTES:
            return None
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_json(path: Path) -> Any:
    """Read JSON from a regular bounded file, returning None on invalid input."""
    text = _read_bounded_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the requested peer-gate operation."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    classify = subparsers.add_parser("classify-testthat")
    classify.add_argument("--log", type=Path, required=True)
    classify.add_argument("--package", required=True)
    classify.add_argument("--description", type=Path)

    require_check = subparsers.add_parser("require-check")
    require_check.add_argument("--checks-json", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the selected R coverage peer-evidence gate."""
    args = parse_args(argv)
    if args.command == "classify-testthat":
        text = _read_bounded_text(args.log)
        allowed_missing: set[str] | None = set()
        if args.description is not None:
            description = _read_bounded_text(args.description)
            allowed_missing = (
                declared_suggests(description) if description is not None else None
            )
        if (
            text is not None
            and allowed_missing is not None
            and classify_testthat_failure(
                text,
                args.package,
                allowed_missing=allowed_missing,
            )
        ):
            print(
                "testthat failures were exclusively packageNotFoundError conditions "
                f"for package {args.package} or its declared Suggests dependencies"
            )
            return 0
        print("testthat failure is not safely deferrable", file=sys.stderr)
        return 1

    checks = _read_json(args.checks_json)
    if has_successful_r_cmd_check(checks):
        print("successful current-head R CMD check evidence found")
        return 0
    print("successful current-head R CMD check evidence was not found", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
