#!/usr/bin/env python3
"""Redact credentials from CI log text before it becomes review evidence."""

from __future__ import annotations

import base64
import json
import re
import shlex
import sys
import unicodedata
from collections.abc import Sequence
from typing import Any

REDACTED = "[REDACTED]"
KEY_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-")
ANSI_ESCAPE_RE = re.compile(
    r"(?:\x1b\[|\x9b)[0-?]*[ -/]*[@-~]"
    r"|(?:\x1b\]|\x9d)[^\x1b\x07\x9c]*(?:\x07|\x9c|\x1b\\)"
    r"|(?:\x1b[PX^_]|\x90|\x98|\x9e|\x9f)[^\x1b\x9c]*(?:\x9c|\x1b\\)"
    r"|(?:\x1b\]|\x1b[PX^_]|\x90|\x98|\x9d|\x9e|\x9f)[\s\S]*\Z"
    r"|\x1b[ -/]*[0-~]"
    r"|[\x80-\x84\x86-\x8f\x91-\x9a\x9c]"
)
SGR_ESCAPE_RE = re.compile(r"(?:\x1b\[|\x9b)[0-9:;]*m")
UNSAFE_INLINE_CONTROL_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x84\x86-\x9f]"
)
LINE_SEPARATOR_RE = re.compile(r"\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029]")
LINE_SEPARATOR_END_RE = re.compile(
    r"(?:\r\n|[\n\r\v\f\x1c-\x1e\x85\u2028\u2029])\Z"
)
CAMEL_ACRONYM_BOUNDARY_RE = re.compile(r"(?<=[A-Z])(?=[A-Z][a-z])")
CAMEL_WORD_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
NON_KEY_WORD_RE = re.compile(r"[^A-Za-z0-9]+")
SENSITIVE_KEY_TERMS = frozenset(
    {
        "auth",
        "authorization",
        "credential",
        "credentials",
        "jwt",
        "passwd",
        "password",
        "secret",
        "token",
    }
)
SENSITIVE_KEY_PAIRS = frozenset(
    {
        ("access", "key"),
        ("api", "key"),
        ("connection", "string"),
        ("database", "url"),
        ("encryption", "key"),
        ("private", "key"),
        ("secret", "key"),
        ("session", "key"),
        ("signing", "key"),
    }
)
SENSITIVE_JOINED_KEY_TERMS = frozenset(
    "".join(pair) for pair in SENSITIVE_KEY_PAIRS
)
BENIGN_JOINED_KEY_TERMS = frozenset({"notsecret", "retoken"})
SAFE_METADATA_SUFFIXES = frozenset(
    {
        ("budget",),
        ("count",),
        ("decode", "error"),
        ("expires", "at"),
        ("failure", "reason"),
        ("policy",),
        ("policy", "status"),
        ("rotation", "status"),
        ("scan", "count"),
        ("status",),
        ("type",),
        ("usage",),
    }
)
JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{3,}\.[A-Za-z0-9_-]{3,}\."
    r"[A-Za-z0-9_-]{3,}(?![A-Za-z0-9_-])"
)
AUTHORIZATION_HEADER_RE = re.compile(
    r"(?P<prefix>\b(?:proxy-)?authorization\s*:\s*)[^\r\n]+",
    re.IGNORECASE,
)
BEARER_RE = re.compile(
    r"(?P<prefix>\b(?:bearer|basic)\s+)"
    r"[^\s\"'\\]+",
    re.IGNORECASE,
)
URL_CREDENTIAL_RE = re.compile(
    r"(?P<scheme>\b[a-z][a-z0-9+.-]*://)[^/\s:@]*:[^@\s/]+@",
    re.IGNORECASE,
)
PRIVATE_KEY_PEM_RE = re.compile(
    r"-----BEGIN (?P<label>[A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?)-----[\s\S]*?"
    r"-----END (?P=label)-----"
    r"|-----BEGIN [A-Z0-9 ]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*\Z"
)
DEFAULT_IGNORABLE_RANGES = (
    (0x034F, 0x034F),
    (0x115F, 0x1160),
    (0x17B4, 0x17B5),
    (0x180B, 0x180F),
    (0x2065, 0x2065),
    (0x3164, 0x3164),
    (0xFE00, 0xFE0F),
    (0xFFA0, 0xFFA0),
    (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A),
    (0xE0000, 0xE0FFF),
)
SENSITIVE_COMMAND_OPTIONS = frozenset(
    {
        "auth",
        "oauth2-bearer",
        "proxy-user",
        "u",
        "user",
        "user-pass",
        "user-password",
        "userpass",
    }
)
CONTAINER_LOGIN_PROGRAMS = frozenset({"docker", "podman"})
PROVIDER_TOKEN_RES = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)


def _word_identifies_credentials(word: str) -> bool:
    """Return whether one key word contains a credential-denoting signal."""
    signals = SENSITIVE_KEY_TERMS | SENSITIVE_JOINED_KEY_TERMS
    return word not in BENIGN_JOINED_KEY_TERMS and any(
        (word == signal if signal == "auth" else signal in word)
        for signal in signals
    )


def _key_identifies_credentials(value: object) -> bool:
    """Return whether a structured key denotes a credential value rather than metadata."""
    expanded = CAMEL_ACRONYM_BOUNDARY_RE.sub("_", _strip_ansi(str(value)))
    expanded = CAMEL_WORD_BOUNDARY_RE.sub("_", expanded)
    words = tuple(word for word in NON_KEY_WORD_RE.split(expanded.lower()) if word)
    if not words:
        return False
    signal_end = 0
    for index, word in enumerate(words):
        if _word_identifies_credentials(word):
            signal_end = index + 1
        if index and words[index - 1 : index + 1] in SENSITIVE_KEY_PAIRS:
            signal_end = index + 1
    if not signal_end:
        return False
    return words[signal_end:] not in SAFE_METADATA_SUFFIXES


def _strip_ansi(text: str) -> str:
    """Remove terminal escape sequences before credential-shape matching."""
    return ANSI_ESCAPE_RE.sub("", text)


def _strip_safe_ansi(text: str) -> str:
    """Remove styling and replace unsafe escape payloads on every affected line."""
    def replacement(match: re.Match[str]) -> str:
        """Return one unsafe-control sentinel for every affected logical line."""
        sequence = match.group(0)
        if SGR_ESCAPE_RE.fullmatch(sequence):
            return ""
        output = ["\x00"]
        for separator in LINE_SEPARATOR_RE.finditer(sequence):
            output.extend((separator.group(0), "\x00"))
        return "".join(output)

    return ANSI_ESCAPE_RE.sub(
        replacement,
        text,
    )


def _contains_unsafe_render_controls(text: str) -> bool:
    """Return whether text can alter or invisibly split its rendered representation."""
    for match in ANSI_ESCAPE_RE.finditer(text):
        if SGR_ESCAPE_RE.fullmatch(match.group(0)) is None:
            return True
    visible = ANSI_ESCAPE_RE.sub("", text)
    return UNSAFE_INLINE_CONTROL_RE.search(visible) is not None or any(
        unicodedata.category(char) == "Cf"
        or any(start <= ord(char) <= end for start, end in DEFAULT_IGNORABLE_RANGES)
        for char in visible
    )


def _literal_replacement(value: str) -> str:
    """Return one marker while retaining separators in their original positions."""
    output: list[str] = []
    cursor = 0
    marker_added = False
    for match in LINE_SEPARATOR_RE.finditer(value):
        if match.start() > cursor and not marker_added:
            output.append(REDACTED)
            marker_added = True
        output.append(match.group(0))
        cursor = match.end()
    if cursor < len(value) and not marker_added:
        output.append(REDACTED)
        marker_added = True
    return "".join(output) if marker_added else value


def _canonical_sensitive_values(sensitive_values: Sequence[str]) -> tuple[str, ...]:
    """Normalize and de-duplicate literal credentials once per redaction call."""
    canonical_values: set[str] = set()
    for original in sensitive_values:
        for value in {original, _strip_ansi(original)}:
            if not value:
                continue
            canonical_values.add(value)
            represented = repr(value)
            canonical_values.add(represented[1:-1])
            canonical_values.add(json.dumps(value, ensure_ascii=True)[1:-1])
            canonical_values.add(json.dumps(value, ensure_ascii=False)[1:-1])
    return tuple(
        sorted(
            (value for value in canonical_values if value),
            key=lambda value: (-len(value), value),
        )
    )


def _compile_literal_pattern(values: Sequence[str]) -> re.Pattern[str] | None:
    """Compile one marker-safe matcher for caller-supplied literal credentials."""
    if not values:
        return None
    sensitive_alternatives = "|".join(re.escape(value) for value in values)
    return re.compile(
        f"(?P<marker>{re.escape(REDACTED)})|"
        f"(?P<sensitive>{sensitive_alternatives})"
    )


def _redact_literal_values(
    text: str,
    literal_pattern: re.Pattern[str] | None,
) -> str:
    """Replace literal credentials against the original text in one pass."""
    if literal_pattern is None:
        return text
    return literal_pattern.sub(
        lambda match: (
            match.group(0)
            if match.group("marker") is not None
            else _literal_replacement(match.group("sensitive"))
        ),
        text,
    )


def _redact_json(
    value: Any,
    literal_pattern: re.Pattern[str] | None,
    redact_literal_keys: bool,
) -> Any:
    """Recursively replace values whose JSON keys identify credentials."""
    if isinstance(value, dict):
        cleaned: dict[Any, Any] = {}
        collision_counts: dict[str, int] = {}
        for key, item in value.items():
            key_identifies_credentials = _key_identifies_credentials(key)
            key_has_unsafe_controls = (
                isinstance(key, str) and _contains_unsafe_render_controls(key)
            )
            cleaned_key = (
                _redact_unstructured(
                    key,
                    literal_pattern if redact_literal_keys else None,
                )
                if isinstance(key, str)
                else key
            )
            if cleaned_key in cleaned and isinstance(cleaned_key, str):
                collision_index = collision_counts.get(cleaned_key, 2)
                while f"{cleaned_key}#{collision_index}" in cleaned:
                    collision_index += 1
                collision_counts[cleaned_key] = collision_index + 1
                cleaned_key = f"{cleaned_key}#{collision_index}"
            cleaned[cleaned_key] = (
                REDACTED
                if (
                    key_identifies_credentials
                    or _key_identifies_credentials(cleaned_key)
                    or key_has_unsafe_controls
                )
                else _redact_json(item, literal_pattern, redact_literal_keys)
            )
        return cleaned
    if isinstance(value, list):
        return [
            _redact_json(item, literal_pattern, redact_literal_keys)
            for item in value
        ]
    if isinstance(value, str):
        return _redact_unstructured(value, literal_pattern)
    return value


def redact_json_value(
    value: Any,
    *,
    sensitive_values: Sequence[str] = (),
    redact_literal_keys: bool = True,
) -> Any:
    """Return a recursively redacted JSON-compatible value without serializing it."""
    values = _canonical_sensitive_values(sensitive_values)
    return _redact_json(
        value,
        _compile_literal_pattern(values),
        redact_literal_keys,
    )


def _command_option_identifies_credentials(argument: str) -> bool:
    """Return whether an argv element expects a separate credential value."""
    if not argument.startswith("-") or "=" in argument:
        return False
    option = argument.lstrip("-")
    return bool(option) and (
        option.lower() in SENSITIVE_COMMAND_OPTIONS
        or _key_identifies_credentials(option)
    )


def _command_program(argument: str) -> str:
    """Return the basename used for program-aware evidence handling."""
    return argument.rsplit("/", 1)[-1].lower()


def _container_login_password_option(
    command: Sequence[str],
    index: int,
    argument: str,
) -> bool:
    """Identify Docker/Podman login's ambiguous short password option."""
    option = argument.partition("=")[0]
    return (
        option == "-p"
        and _command_program(command[0]) in CONTAINER_LOGIN_PROGRAMS
        and "login" in command[1:index]
    )


def redact_command_argv(
    command: Sequence[str],
    *,
    sensitive_values: Sequence[str] = (),
) -> list[str]:
    """Redact argv, including values following credential-denoting options."""
    values = _canonical_sensitive_values(sensitive_values)
    literal_pattern = _compile_literal_pattern(values)
    cleaned: list[str] = []
    redact_next = False
    for index, argument in enumerate(command):
        if redact_next:
            cleaned.append(REDACTED)
            redact_next = False
            continue
        option, separator, _value = argument.partition("=")
        if (
            separator
            and option.startswith("-")
            and (
                _command_option_identifies_credentials(option)
                or _container_login_password_option(command, index, argument)
            )
        ):
            cleaned.append(f"{option}={REDACTED}")
            continue
        cleaned.append(_redact_unstructured(argument, literal_pattern))
        redact_next = (
            _command_option_identifies_credentials(argument)
            or _container_login_password_option(command, index, argument)
        )
    return cleaned


def redact_command_text(
    command: str,
    *,
    sensitive_values: Sequence[str] = (),
) -> str:
    """Redact a shell-like command string without changing the executed command."""
    cleaned_command = redact_text(command, sensitive_values=sensitive_values)
    try:
        arguments = shlex.split(cleaned_command)
    except ValueError:
        rough_arguments = cleaned_command.split()
        if any(
            _command_option_identifies_credentials(argument)
            for argument in rough_arguments
        ):
            return REDACTED
        return cleaned_command
    return shlex.join(
        redact_command_argv(arguments, sensitive_values=sensitive_values)
    )


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
    if not _key_identifies_credentials(key):
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
        char = text[cursor]
        if char in "\"'":
            next_cursor = cursor + 1
        elif (
            char not in KEY_CHARS
            or char.isdigit()
            or (cursor > 0 and text[cursor - 1] in KEY_CHARS)
        ):
            cursor += 1
            continue
        else:
            next_cursor = cursor + 1
            while next_cursor < len(text) and text[next_cursor] in KEY_CHARS:
                next_cursor += 1
        match = _consume_sensitive_assignment(text, cursor)
        if match is None:
            cursor = next_cursor
            continue
        output.append(text[last_append:cursor])
        replacement, cursor = match
        output.append(replacement)
        last_append = cursor
    output.append(text[last_append:])
    return "".join(output)


def _redact_unstructured(
    text: str,
    literal_pattern: re.Pattern[str] | None = None,
) -> str:
    """Redact credential-shaped values from non-JSON diagnostic text."""
    if _contains_unsafe_render_controls(text):
        return REDACTED
    cleaned = _strip_ansi(text)
    cleaned = _redact_literal_values(cleaned, literal_pattern)
    cleaned = URL_CREDENTIAL_RE.sub(
        lambda match: f"{match.group('scheme')}{REDACTED}@",
        cleaned,
    )
    cleaned = AUTHORIZATION_HEADER_RE.sub(
        lambda match: f"{match.group('prefix')}{REDACTED}",
        cleaned,
    )
    cleaned = BEARER_RE.sub(lambda match: f"{match.group('prefix')}{REDACTED}", cleaned)
    cleaned = _redact_assignments(cleaned)
    cleaned = JWT_RE.sub(_redact_jwt_candidate, cleaned)
    for pattern in PROVIDER_TOKEN_RES:
        cleaned = pattern.sub(REDACTED, cleaned)
    return cleaned


def _redact_jwt_candidate(match: re.Match[str]) -> str:
    """Redact a JWT only when its first segment is a valid JOSE header."""
    candidate = match.group(0)
    header = candidate.split(".", 1)[0]
    padding = "=" * (-len(header) % 4)
    try:
        decoded_header = json.loads(base64.urlsafe_b64decode(header + padding))
    except (ValueError, RecursionError):
        return candidate
    if isinstance(decoded_header, dict) and isinstance(decoded_header.get("alg"), str):
        return REDACTED
    return candidate


def _redact_line(
    line: str,
    json_literal_pattern: re.Pattern[str] | None,
    unstructured_literal_pattern: re.Pattern[str] | None,
) -> str:
    """Redact one log line, preferring recursive JSON handling when valid."""
    try:
        value = json.loads(line)
        cleaned = _redact_json(value, json_literal_pattern, True)
    except (ValueError, RecursionError):
        return _redact_unstructured(line, unstructured_literal_pattern)
    return json.dumps(
        cleaned,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def redact_text(text: str, *, sensitive_values: Sequence[str] = ()) -> str:
    """Return redacted log text while preserving line boundaries."""
    if not text:
        return text
    text = _strip_safe_ansi(text)
    text = PRIVATE_KEY_PEM_RE.sub(
        lambda match: _literal_replacement(match.group(0)),
        text,
    )
    values = _canonical_sensitive_values(sensitive_values)
    json_literal_pattern = _compile_literal_pattern(values)
    single_line_values = tuple(
        value for value in values if LINE_SEPARATOR_RE.search(value) is None
    )
    multiline_values = tuple(
        value for value in values if LINE_SEPARATOR_RE.search(value) is not None
    )
    unstructured_literal_pattern = _compile_literal_pattern(single_line_values)
    text = _redact_literal_values(text, _compile_literal_pattern(multiline_values))
    output: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        separator = LINE_SEPARATOR_END_RE.search(raw_line)
        if separator is None:
            line = raw_line
            ending = ""
        else:
            line = raw_line[: separator.start()]
            ending = separator.group(0)
        output.append(
            _redact_line(
                line,
                json_literal_pattern,
                unstructured_literal_pattern,
            )
            + ending
        )
    return "".join(output)


def main() -> int:
    """Redact standard input to standard output."""
    sys.stdout.write(redact_text(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
