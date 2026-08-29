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
    r"(^|[^A-Za-z0-9_-])[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\."
    r"[A-Za-z0-9_-]{3,}($|[^A-Za-z0-9_-])"
)
BEARER_RE = re.compile(
    r"(?P<prefix>\b(?:authorization\s*:\s*)?(?:bearer|basic)\s+)"
    r"[^\s\"'\\]+",
    re.IGNORECASE,
)
PROVIDER_TOKEN_RES = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
EMAIL_RE = re.compile(
    r"(^|[^\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}($|[^\w.-])"
)
PHONE_RE = re.compile(
    r"(^|[^\w])(?:\+\d[\d(). -]{7,}\d|\d{2,4}[-. ]\d{3,4}[-. ]\d{3,4})"
    r"($|[^\w])"
)
IPV4_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
IPV4_RE = re.compile(
    rf"(^|[^\d.])((?:{IPV4_OCTET}\.){{3}}{IPV4_OCTET})($|[^\d.])"
)
RUNNER_PATH_RE = re.compile(
    r"(^|[^\w:])/(?:Users|home|runner|private/tmp|tmp)/[^\s`\"']+"
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
    if isinstance(value, str):
        return _redact_unstructured(value)
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
            if text[cursor] in KEY_CHARS:
                while cursor < len(text) and text[cursor] in KEY_CHARS:
                    cursor += 1
            else:
                cursor += 1
            continue
        output.append(text[last_append:cursor])
        replacement, cursor = match
        output.append(replacement)
        last_append = cursor
    output.append(text[last_append:])
    return "".join(output)


def _redact_unstructured(text: str, *, redact_assignments: bool = True) -> str:
    """Redact credential-shaped and allowlisted operational identifiers."""
    cleaned = _redact_assignments(text) if redact_assignments else text
    cleaned = BEARER_RE.sub(lambda match: f"{match.group('prefix')}{REDACTED}", cleaned)
    cleaned = JWT_RE.sub(
        lambda match: f"{match.group(1)}{REDACTED}{match.group(2)}", cleaned
    )
    for pattern in PROVIDER_TOKEN_RES:
        cleaned = pattern.sub(REDACTED, cleaned)
    return _redact_operational_identifiers(cleaned)


def _redact_operational_identifiers(text: str) -> str:
    """Apply the minimum-disclosure allowlist to common operational PII."""
    cleaned = _redact_bounded_matches(text, EMAIL_RE, "[REDACTED_EMAIL]")
    cleaned = _redact_bounded_matches(cleaned, PHONE_RE, "[REDACTED_PHONE]")
    cleaned = _redact_ipv4_addresses(cleaned)
    return RUNNER_PATH_RE.sub(r"\1[REDACTED_PATH]", cleaned)


def _redact_bounded_matches(text: str, pattern: re.Pattern[str], replacement: str) -> str:
    """Replace bounded matches while leaving each trailing delimiter searchable."""
    pieces: list[str] = []
    cursor = 0
    search_from = 0
    while True:
        match = pattern.search(text, search_from)
        if match is None:
            pieces.append(text[cursor:])
            return "".join(pieces)
        prefix = match.group(1)
        suffix = match.group(2)
        value_end = match.end(2) - len(suffix)
        pieces.extend((text[cursor : match.start(1)], prefix, replacement))
        cursor = value_end
        search_from = value_end


def _redact_ipv4_addresses(text: str) -> str:
    """Redact IPv4 values while keeping delimiters available to later matches."""
    pieces: list[str] = []
    cursor = 0
    search_from = 0
    while True:
        match = IPV4_RE.search(text, search_from)
        if match is None:
            pieces.append(text[cursor:])
            return "".join(pieces)
        ip_start, ip_end = match.span(2)
        pieces.extend((text[cursor:ip_start], "[REDACTED_IP]"))
        cursor = ip_end
        search_from = ip_end


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
