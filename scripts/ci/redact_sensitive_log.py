"""Redact credential-shaped values before publishing subprocess evidence."""

from __future__ import annotations

import json
import re
import shlex
from typing import Any, Sequence


REDACTED = "[REDACTED]"
SENSITIVE_KEY_RE = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?key|auth|authorization|bearer|credential|jwt|password|passwd|private[_-]?key|secret|session[_-]?key|token)"
)
SENSITIVE_OPTION_RE = re.compile(
    r"(?i)^--?(?:api[_-]?key|auth|authorization|bearer|credential|password|passwd|private[_-]?key|secret|session[_-]?key|token)$"
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)(\b[A-Za-z_][A-Za-z0-9_-]*(?:API[_-]?KEY|AUTH|AUTHORIZATION|BEARER|CREDENTIAL|PASSWORD|PASSWD|PRIVATE[_-]?KEY|SECRET|SESSION[_-]?KEY|TOKEN)[A-Za-z0-9_-]*\s*[=:]\s*)([^\s,;]+)"
)
BEARER_BASIC_RE = re.compile(r"(?i)\b(Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+")
JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b"
)
PROVIDER_TOKEN_RES = (
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bASIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bnvapi-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)
MAX_IDENTIFIER_CHARS = 4096
MAX_JSON_DEPTH = 64


def _redact_scalar(value: str) -> str:
    """Redact one scalar that may itself be a credential."""
    redacted = SENSITIVE_ASSIGNMENT_RE.sub(lambda match: match.group(1) + REDACTED, value)
    redacted = BEARER_BASIC_RE.sub(lambda match: f"{match.group(1)} {REDACTED}", redacted)
    redacted = JWT_RE.sub(REDACTED, redacted)
    for pattern in PROVIDER_TOKEN_RES:
        redacted = pattern.sub(REDACTED, redacted)
    return redacted


def _consume_json_string(text: str, start: int, *, depth: int) -> tuple[str, int] | None:
    """Return one decoded/redacted JSON string and the first following index."""
    cursor = start + 1
    escaped = False
    while cursor < len(text):
        character = text[cursor]
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            candidate = text[start : cursor + 1]
            try:
                decoded = json.loads(candidate)
            except json.JSONDecodeError:
                return None
            if not isinstance(decoded, str):
                return None
            redacted = _redact_unstructured(decoded, depth=depth + 1)
            return json.dumps(redacted, ensure_ascii=False), cursor + 1
        cursor += 1
    return None


def _consume_sensitive_assignment(text: str, start: int) -> tuple[str | None, int]:
    """Inspect one identifier once and redact its assigned scalar when sensitive.

    The returned index advances beyond the complete identifier that was already
    classified. Identifiers larger than :data:`MAX_IDENTIFIER_CHARS` are never
    copied into the credential-key matcher; when followed by an assignment they
    are handled conservatively as sensitive. This preserves linear scanning,
    bounds classification work, and prevents an oversized key from becoming a
    redaction bypass.
    """
    if not (text[start].isalpha() or text[start] == "_"):
        return None, start + 1

    cursor = start + 1
    while cursor < len(text) and (text[cursor].isalnum() or text[cursor] in "_-"):
        cursor += 1

    assignment_cursor = cursor
    while assignment_cursor < len(text) and text[assignment_cursor].isspace():
        assignment_cursor += 1
    if assignment_cursor >= len(text) or text[assignment_cursor] not in "=:":
        return None, cursor

    key_length = cursor - start
    is_sensitive = key_length > MAX_IDENTIFIER_CHARS or bool(
        SENSITIVE_KEY_RE.search(text[start:cursor])
    )
    if not is_sensitive:
        return None, cursor

    value_start = assignment_cursor + 1
    while value_start < len(text) and text[value_start].isspace():
        value_start += 1
    if value_start >= len(text):
        return None, cursor

    prefix = text[start:value_start]
    if text[value_start] in {'"', "'"}:
        quote = text[value_start]
        value_end = value_start + 1
        escaped = False
        while value_end < len(text):
            character = text[value_end]
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                return prefix + quote + REDACTED + quote, value_end + 1
            value_end += 1
        return prefix + quote + REDACTED, len(text)

    value_end = value_start
    while value_end < len(text) and not text[value_end].isspace() and text[value_end] not in ",;}":
        value_end += 1
    return prefix + REDACTED, value_end


def _redact_unstructured(text: str, *, depth: int = 0) -> str:
    """Redact arbitrary diagnostic text without invoking a shell or regex loop."""
    if depth > 8:
        return _redact_scalar(text)

    output: list[str] = []
    cursor = 0
    plain_start = 0
    while cursor < len(text):
        if text[cursor] == '"':
            parsed = _consume_json_string(text, cursor, depth=depth)
            if parsed is not None:
                replacement, next_cursor = parsed
                output.append(_redact_scalar(text[plain_start:cursor]))
                output.append(replacement)
                cursor = next_cursor
                plain_start = cursor
                continue
        replacement, next_cursor = _consume_sensitive_assignment(text, cursor)
        if replacement is not None:
            output.append(_redact_scalar(text[plain_start:cursor]))
            output.append(replacement)
            cursor = next_cursor
            plain_start = cursor
            continue
        cursor = max(cursor + 1, next_cursor)

    output.append(_redact_scalar(text[plain_start:]))
    return "".join(output)


def _redact_json(value: Any, *, depth: int = 0) -> Any:
    """Return a recursively redacted JSON-compatible value with bounded depth.

    A subtree at or beyond :data:`MAX_JSON_DEPTH` is replaced wholesale rather
    than recursed into. This keeps untrusted structured diagnostics from using
    extreme nesting to exhaust the publication boundary or to bypass secret
    handling through a recursion failure.
    """
    if depth >= MAX_JSON_DEPTH:
        return REDACTED
    if isinstance(value, dict):
        redacted_mapping: dict[str, Any] = {}
        for key, nested in value.items():
            redacted_key = _redact_unstructured(str(key))
            if SENSITIVE_KEY_RE.search(str(key)):
                redacted_mapping[redacted_key] = REDACTED
            else:
                redacted_mapping[redacted_key] = _redact_json(
                    nested,
                    depth=depth + 1,
                )
        return redacted_mapping
    if isinstance(value, list):
        return [_redact_json(item, depth=depth + 1) for item in value]
    if isinstance(value, str):
        return _redact_unstructured(value)
    return value


def redact_text(text: str) -> str:
    """Return text with recognized credential forms removed.

    Valid JSON lines are traversed recursively so a token stored under an
    ordinary key, or used as an object key, cannot bypass line-oriented
    patterns. Deeply nested JSON that exceeds the parser or encoder recursion
    boundary is replaced as one redacted line, preserving confidentiality and
    bounded availability instead of falling back to a weaker parser.
    """
    redacted_lines: list[str] = []
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        line_ending = line[len(stripped) :]
        if stripped and stripped[0] in "[{":
            try:
                parsed = json.loads(stripped)
                encoded = json.dumps(
                    _redact_json(parsed),
                    separators=(",", ":"),
                    ensure_ascii=False,
                )
            except json.JSONDecodeError:
                redacted_lines.append(_redact_unstructured(stripped) + line_ending)
            except RecursionError:
                redacted_lines.append(REDACTED + line_ending)
            else:
                redacted_lines.append(encoded + line_ending)
        else:
            redacted_lines.append(_redact_unstructured(stripped) + line_ending)
    if not text:
        return ""
    if not redacted_lines:
        return _redact_unstructured(text)
    return "".join(redacted_lines)


def _redact_assignment(argument: str) -> str:
    """Redact a sensitive ``KEY=value`` or ``--option=value`` argument."""
    if "=" not in argument:
        return argument
    key, separator, value = argument.partition("=")
    if value and (SENSITIVE_KEY_RE.search(key) or SENSITIVE_OPTION_RE.match(key)):
        return f"{key}{separator}{REDACTED}"
    return argument


def redact_command_arguments(arguments: Sequence[str]) -> list[str]:
    """Return a printable argument vector with sensitive values removed."""
    redacted: list[str] = []
    redact_next = False
    for argument in arguments:
        if redact_next:
            redacted.append(REDACTED)
            redact_next = False
            continue
        assigned = _redact_assignment(str(argument))
        if assigned != argument:
            redacted.append(assigned)
            continue
        if SENSITIVE_OPTION_RE.match(str(argument)):
            redacted.append(str(argument))
            redact_next = True
            continue
        redacted.append(_redact_unstructured(str(argument)))
    return redacted


def redact_shell_command(command: str) -> str:
    """Return a printable shell command while preserving the command execution."""
    try:
        arguments = shlex.split(command, posix=True)
    except ValueError:
        return _redact_unstructured(command)
    return shlex.join(redact_command_arguments(arguments))
