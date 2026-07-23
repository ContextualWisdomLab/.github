#!/usr/bin/env python3
"""Redact credentials from CI log text before it becomes review evidence."""

from __future__ import annotations

import json
import re
import sys
from typing import Any

REDACTED = "[REDACTED]"
KEY_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")
SENSITIVE_KEY_RE = re.compile(
    r"(?:token|secret|password|passwd|credential|authorization|jwt|"
    r"api[_-]?key|private[_-]?key|access[_-]?key|session[_-]?key)",
    re.IGNORECASE,
)
JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\."
    r"[A-Za-z0-9_-]{3,}(?![A-Za-z0-9_-])"
)
BEARER_RE = re.compile(
    r"(?P<prefix>\b(?:authorization\s*:\s*)?(?:bearer|basic)\s+)"
    r"[^\s\"'\\]+",
    re.IGNORECASE,
)
PROVIDER_TOKEN_RES = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _redact_json(value: Any) -> Any:
    """Recursively replace values whose JSON keys identify credentials."""
    if isinstance(value, dict):
        return {
            key: REDACTED if SENSITIVE_KEY_RE.search(str(key)) else _redact_json(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    return value


def _consume_sensitive_assignment(text: str, start: int) -> tuple[str, int] | int:
    """Return a redacted assignment, or the next index to scan if no match."""
    cursor = start
    key_quote = ""
    length = len(text)
    if cursor < length and text[cursor] in "\"'":
        key_quote = text[cursor]
        cursor += 1
    key_start = cursor
    if cursor >= length or text[cursor] not in KEY_CHARS or text[cursor].isdigit():
        return start + 1
    while cursor < length and text[cursor] in KEY_CHARS:
        cursor += 1
    key = text[key_start:cursor]
    if key_quote:
        if cursor >= length or text[cursor] != key_quote:
            return start + 1
        cursor += 1
    if not SENSITIVE_KEY_RE.search(key):
        return cursor
    while cursor < length and text[cursor].isspace():
        cursor += 1
    if cursor >= length or text[cursor] not in ":=":
        return cursor
    cursor += 1
    while cursor < length and text[cursor].isspace():
        cursor += 1
    if cursor >= length:
        return cursor

    value_start = cursor
    if text[cursor] in "\"'":
        value_quote = text[cursor]
        cursor += 1
        escaped = False
        while cursor < length:
            char = text[cursor]
            cursor += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == value_quote:
                break
    else:
        while cursor < length and not text[cursor].isspace() and text[cursor] not in ",}":
            cursor += 1
    if cursor == value_start:
        return cursor
    return text[start:value_start] + REDACTED, cursor


def _redact_assignments(text: str) -> str:
    """Redact sensitive key/value assignments without backtracking regexes."""
    output: list[str] = []
    cursor = 0
    last_append = 0
    length = len(text)
    while cursor < length:
        result = _consume_sensitive_assignment(text, cursor)
        if isinstance(result, int):
            cursor = result
            continue
        replacement, next_cursor = result
        if cursor > last_append:
            output.append(text[last_append:cursor])
        output.append(replacement)
        cursor = next_cursor
        last_append = cursor
    if last_append < length:
        output.append(text[last_append:])
    return "".join(output)


def _redact_unstructured(text: str) -> str:
    """Redact credential-shaped values from non-JSON diagnostic text."""
    cleaned = _redact_assignments(text)
    cleaned = BEARER_RE.sub(lambda match: f"{match.group('prefix')}{REDACTED}", cleaned)
    cleaned = JWT_RE.sub(REDACTED, cleaned)
    for pattern in PROVIDER_TOKEN_RES:
        cleaned = pattern.sub(REDACTED, cleaned)
    return cleaned


def _redact_line(line: str) -> str:
    """Redact one log line, preferring recursive JSON handling when valid."""
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return _redact_unstructured(line)
    return json.dumps(_redact_json(value), ensure_ascii=False, separators=(",", ":"))


def redact_text(text: str) -> str:
    """Return redacted log text while preserving line boundaries."""
    if not text:
        return text
    output: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        ending = raw_line[len(line) :]
        output.append(_redact_line(line) + ending)
    return "".join(output)


def main() -> int:
    """Redact standard input to standard output."""
    sys.stdout.write(redact_text(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
