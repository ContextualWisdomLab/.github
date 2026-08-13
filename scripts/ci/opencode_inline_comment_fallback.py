#!/usr/bin/env python3
"""Render a GitHub 422 inline-comment fallback that cites trusted path:line."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

ERROR_PHRASE_MAX_CHARS = 240
HTTP_422_LINE_RE = re.compile(r"(?im)^(?:gh:\s*)?(.*HTTP 422.*)$")


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


def trusted_finding_locations(control: dict[str, Any]) -> list[tuple[str, int]]:
    """Return unique sanitized finding path:line pairs in first-seen order."""
    findings = control.get("findings")
    if not isinstance(findings, list):
        return []
    locations: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        path = safe_finding_path(finding.get("path"))
        line = safe_finding_line(finding.get("line"))
        if path is None or line is None:
            continue
        location = (path, line)
        if location in seen:
            continue
        seen.add(location)
        locations.append(location)
    return locations


def _collapse_error_text(text: str) -> str:
    """Return one-line error text without URLs or extra whitespace."""
    without_urls = re.sub(r"https?://\S+", "", text)
    return " ".join(without_urls.split())


def escape_receipt_text(text: str) -> str:
    """Escape HTML and Markdown metacharacters in a receipt phrase."""
    escaped = text
    for character, replacement in (
        ("`", "\\u0060"),
        ("<", "\\u003c"),
        (">", "\\u003e"),
        ("&", "\\u0026"),
    ):
        escaped = escaped.replace(character, replacement)
    return escaped


def github_publication_error_phrase(text: str) -> str:
    """Return a bounded GitHub 422 phrase from ``gh api`` stderr or JSON."""
    raw = text or ""
    messages: list[str] = []
    seen: set[str] = set()
    decoder = json.JSONDecoder()
    index = 0
    while index < len(raw):
        start = raw.find("{", index)
        if start < 0:
            break
        try:
            value, consumed = decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue
        index = start + consumed
        errors = value.get("errors")
        if not isinstance(errors, list):
            continue
        for item in errors:
            if not isinstance(item, dict) or not isinstance(item.get("message"), str):
                continue
            message = _collapse_error_text(item["message"])
            if not message or message in seen:
                continue
            seen.add(message)
            messages.append(message)
    if messages:
        phrase = f"GitHub HTTP 422: {'; '.join(messages)}"
    else:
        match = HTTP_422_LINE_RE.search(raw)
        if match:
            line = _collapse_error_text(match.group(1))
            if line.casefold().startswith("github http 422"):
                phrase = line
            else:
                phrase = f"GitHub HTTP 422: {line}".rstrip(": ")
        else:
            phrase = "GitHub review write failed"
    return escape_receipt_text(phrase[:ERROR_PHRASE_MAX_CHARS])


def render_inline_comment_receipts(
    locations: list[tuple[str, int]], error_phrase: str
) -> list[str]:
    """Return durable overview receipt lines for refused inline comments."""
    if not locations:
        return []
    if error_phrase:
        safe_phrase = escape_receipt_text(error_phrase)
        return [f"- `{path}:{line}` — {safe_phrase}" for path, line in locations]
    return [f"- `{path}:{line}`" for path, line in locations]


def render_inline_comment_failure_suffix(
    locations: list[tuple[str, int]],
    *,
    error_phrase: str = "",
) -> str:
    """Return the PR-body suffix used when GitHub rejects inline comments."""
    heading = (
        "## Inline comment publication receipts"
        if error_phrase
        else "## Inline comment publishing failed"
    )
    lines = [
        "",
        heading,
        "",
    ]
    if locations:
        lines.append(
            "GitHub did not accept the inline review comments for these "
            "trusted current-head finding locations:"
        )
        lines.append("")
        lines.extend(render_inline_comment_receipts(locations, error_phrase))
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
        if error_phrase:
            lines.append("")
            lines.append(f"- GitHub error: {escape_receipt_text(error_phrase)}")
    lines.append("")
    return "\n".join(lines)


def render_inline_comment_failure_body(
    body: str,
    control: dict[str, Any],
    *,
    error_text: str = "",
) -> str:
    """Append the 422 fallback suffix to an existing REQUEST_CHANGES body."""
    error_phrase = github_publication_error_phrase(error_text) if error_text else ""
    return body.rstrip("\n") + render_inline_comment_failure_suffix(
        trusted_finding_locations(control),
        error_phrase=error_phrase,
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
    """Write a REQUEST_CHANGES body plus path:line receipts and optional 422 phrase."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control", required=True, type=Path)
    parser.add_argument("--body", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--error-file", type=Path)
    args = parser.parse_args(argv)
    try:
        control = load_control(args.control)
        body = args.body.read_text(encoding="utf-8")
        error_text = (
            args.error_file.read_text(encoding="utf-8") if args.error_file else ""
        )
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    args.output.write_text(
        render_inline_comment_failure_body(body, control, error_text=error_text),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through runpy CLI test
    raise SystemExit(main())
