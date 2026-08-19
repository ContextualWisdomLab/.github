#!/usr/bin/env python3
"""Classify blocking Strix report signals without rejecting benign warnings.

Exit-code contract for the command-line interface:

* ``0`` — at least one blocking signal was found;
* ``1`` — no blocking signal was found;
* ``2`` — invocation error.

The caller remains responsible for classifying provider availability from the
Strix console log. This helper only inspects report artifact ``*.log`` files.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
import os
from pathlib import Path
import re
import sys


_BLOCKING_WORD = re.compile(
    r"(?<![A-Za-z])(?:fatal|denied|timeout)(?![A-Za-z])",
    re.IGNORECASE,
)
_STRIX_LOGGER = re.compile(
    r"(?<![A-Za-z0-9_])strix(?:[._][A-Za-z0-9_:-]+)+",
    re.IGNORECASE,
)
_WARNING_WORD = re.compile(r"(?<![A-Za-z])warning(?![A-Za-z])", re.IGNORECASE)
_FAILURE_SEMANTIC = re.compile(
    r"(?<![A-Za-z])(?:fail(?:ed|ure)?|incomplete|denied|timeout|unavailable)(?![A-Za-z])",
    re.IGNORECASE,
)


def contains_blocking_signal(text: str) -> bool:
    """Return whether report text proves a scanner failure condition.

    Generic third-party warnings are intentionally non-blocking. A warning is
    blocking only when it is emitted through a Strix logger and also carries
    explicit failure semantics. Fatal, denied, and timeout signals remain
    blocking regardless of logger format.
    """
    if _BLOCKING_WORD.search(text):
        return True
    for line in text.splitlines():
        if (
            _WARNING_WORD.search(line)
            and _STRIX_LOGGER.search(line)
            and _FAILURE_SEMANTIC.search(line)
        ):
            return True
    return False


def _iter_report_logs(report_root: Path) -> Iterable[Path]:
    """Yield regular, non-symlink ``*.log`` files below ``report_root``."""
    if not report_root.is_dir() or report_root.is_symlink():
        return
    for current_root, directory_names, file_names in os.walk(
        report_root,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current_root)
        directory_names[:] = [
            directory_name
            for directory_name in directory_names
            if not (current_path / directory_name).is_symlink()
        ]
        for file_name in file_names:
            log_path = current_path / file_name
            if log_path.suffix != ".log" or log_path.is_symlink() or not log_path.is_file():
                continue
            yield log_path


def scan_report_roots(report_roots: Iterable[Path]) -> bool:
    """Return whether any readable report log contains a blocking signal."""
    for report_root in report_roots:
        for log_path in _iter_report_logs(report_root):
            try:
                text = log_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if contains_blocking_signal(text):
                return True
    return False


def main(argv: Sequence[str] | None = None) -> int:
    """Run the report classifier using shell-compatible exit codes."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        print("strix_report_signal.py requires at least one report root", file=sys.stderr)
        return 2
    roots = [Path(argument) for argument in arguments]
    return 0 if scan_report_roots(roots) else 1


if __name__ == "__main__":
    raise SystemExit(main())
