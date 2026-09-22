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
PROVIDER_TOKEN_RE = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"sk-[A-Za-z0-9_-]{20,}|"
    r"xox[baprs]-[A-Za-z0-9-]{20,}|"
    r"AKIA[0-9A-Z]{16}|"
    r"[A-Za-z0-9/+]{40}|"
    r"[A-Za-z0-9/+]{88}|"
    r"sk_(?:test|live)_[A-Za-z0-9]{24,})\b"
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


def _consume_sensitive_assignment(text: str, start: int) -> tuple[str, int] | None:
    """Return a redacted key/value assignment parsed in linear time."""
    cursor = start
    key_quote = ""
    if cursor < len(text) and text[cursor] in "\"'":
        key_quote = text[cursor]
        cursor += 1
    key_start = cursor
    if cursor >= len(text) or text[cursor] not in KEY_CHARS or text[cursor].isdigit():
        return None
    while cursor < len(text) and text[cursor] in KEY_CHARS:
        cursor += 1
    key = text[key_start:cursor]
    if key_quote:
        if cursor >= len(text) or text[cursor] != key_quote:
            return None
        cursor += 1
    if not SENSITIVE_KEY_RE.search(key):
        return None
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text) or text[cursor] not in ":=":
        return None
    cursor += 1
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor >= len(text):
        return None

    value_start = cursor
    if text[cursor] in "\"'":
        value_quote = text[cursor]
        cursor += 1
        escaped = False
        while cursor < len(text):
            char = text[cursor]
            cursor += 1
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == value_quote:
                break
    else:
        while cursor < len(text) and not text[cursor].isspace() and text[cursor] not in ",}":
            cursor += 1
    if cursor == value_start:
        return None
    return text[start:value_start] + REDACTED, cursor


def _redact_assignments(text: str) -> str:
    """Redact sensitive key/value assignments without backtracking regexes."""
    output: list[str] = []
    cursor = 0
    last_append = 0
    while cursor < len(text):
        match = _consume_sensitive_assignment(text, cursor)
        if match is None:
            cursor += 1
            continue
        output.append(text[last_append:cursor])
        replacement, cursor = match
        output.append(replacement)
        last_append = cursor
    output.append(text[last_append:])
    return "".join(output)


def _redact_unstructured(text: str) -> str:
    """Redact credential-shaped values from non-JSON diagnostic text."""
    cleaned = _redact_assignments(text)
    cleaned = BEARER_RE.sub(lambda match: f"{match.group('prefix')}{REDACTED}", cleaned)
    cleaned = JWT_RE.sub(REDACTED, cleaned)
    cleaned = PROVIDER_TOKEN_RE.sub(REDACTED, cleaned)
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
