#!/usr/bin/env python3
"""Render a GitHub 422 inline-comment fallback that cites leftover ranges."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any


def safe_finding_path(raw_path: object) -> str | None:
    """Return a repository-relative finding path, or None when it is unsafe.

    Rejects traversal, absolute and drive paths, backslashes, and characters
    that would break Markdown receipt fences (backtick, ``<``, ``>``, ``&``).
    """
    if not isinstance(raw_path, str):
        return None
    path = raw_path.strip()
    posix_path = PurePosixPath(path)
    windows_path = PureWindowsPath(path)
    if (
        not path
        or "\\" in path
        or path.startswith(("/", "//"))
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or bool(windows_path.drive)
        or ".." in posix_path.parts
        or path != posix_path.as_posix()
        or any(char in path for char in ("`", "<", ">", "&"))
    ):
        return None
    return path


def safe_finding_line(raw_line: object) -> int | None:
    """Return a positive integer finding line, or None when it is not one.

    Control JSON and LLM output often emit ``line`` as a decimal string.
    CWE-20: reject bools, non-decimal text, and non-positive values; accept
    only a positive ``int`` or a digit-only string of that int.
    """
    if isinstance(raw_line, bool):
        return None
    if isinstance(raw_line, int):
        return raw_line if raw_line > 0 else None
    if isinstance(raw_line, str):
        text = raw_line.strip()
        if text.isdigit():
            value = int(text)
            return value if value > 0 else None
    return None


def leftover_finding_range(finding: dict[str, Any]) -> tuple[str, int, int] | None:
    """Return a trusted leftover ``(path, start, end)`` range, or None.

    ``line`` is the last leftover line. ``start_line``, when present, is
    the first leftover line. A start after the end is not a range.
    """
    path = safe_finding_path(finding.get("path"))
    end = safe_finding_line(finding.get("line"))
    if path is None or end is None:
        return None
    start = safe_finding_line(finding.get("start_line"))
    if start is None:
        return (path, end, end)
    if start > end:
        return None
    return (path, start, end)


def format_leftover_range(path: str, start: int, end: int) -> str:
    """Return ``path:line`` or leftover ``path:start-end`` for one finding."""
    if start == end:
        return f"{path}:{end}"
    return f"{path}:{start}-{end}"


def trusted_finding_ranges(control: dict[str, Any]) -> list[tuple[str, int, int]]:
    """Return unique sanitized leftover path:start-end ranges in first-seen order."""
    findings = control.get("findings")
    if not isinstance(findings, list):
        return []
    ranges: list[tuple[str, int, int]] = []
    seen: set[tuple[str, int, int]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        item = leftover_finding_range(finding)
        if item is None or item in seen:
            continue
        seen.add(item)
        ranges.append(item)
    return ranges


def trusted_finding_locations(control: dict[str, Any]) -> list[tuple[str, int]]:
    """Return unique sanitized finding path:line pairs in first-seen order."""
    locations: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for path, _start, end in trusted_finding_ranges(control):
        location = (path, end)
        if location in seen:
            continue
        seen.add(location)
        locations.append(location)
    return locations


def render_inline_comment_failure_suffix(
    locations: list[tuple[str, int, int]],
) -> str:
    """Return the PR-body suffix used when GitHub rejects inline comments."""
    lines = [
        "",
        "## Inline comment publishing failed",
        "",
    ]
    if locations:
        lines.append(
            "GitHub did not accept the inline review comments for these "
            "trusted current-head finding locations:"
        )
        lines.append("")
        lines.extend(
            f"- `{format_leftover_range(path, start, end)}`"
            for path, start, end in locations
        )
        lines.append("")
        lines.append(
            "OpenCode did not copy suggested diffs into this PR-level body. "
            "Re-run the review after those exact path:line anchors sit on "
            "current-head changed hunks, or inspect the workflow log/control "
            "JSON and apply the changes manually."
        )
    else:
        lines.append(
            "GitHub did not accept the inline review comments, and the "
            "control JSON had no trusted path:line findings. Inspect the "
            "workflow log and apply any remaining blockers from the review "
            "body manually."
        )
    lines.append("")
    return "\n".join(lines)


def render_inline_comment_failure_body(body: str, control: dict[str, Any]) -> str:
    """Append the 422 fallback suffix to an existing REQUEST_CHANGES body."""
    return body.rstrip("\n") + render_inline_comment_failure_suffix(
        trusted_finding_ranges(control)
    )


def load_control(path: Path) -> dict[str, Any]:
    """Load one trusted review-control JSON object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"control JSON could not be read: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("control JSON must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    """Write a REQUEST_CHANGES body plus leftover path:start-end 422 suffix."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("--body", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        control = load_control(args.control)
        body = args.body.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    args.output.write_text(
        render_inline_comment_failure_body(body, control), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through runpy CLI test
    raise SystemExit(main())
