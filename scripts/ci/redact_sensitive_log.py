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
COMMAND_WRAPPER_SHELLS = frozenset({"bash", "dash", "ksh", "sh", "zsh"})
COMMAND_EVIDENCE_KEYS = frozenset(
    {"argv", "backend_cmd", "command", "e2e_cmd", "frontend_cmd"}
)
ENV_SPLIT_OPTIONS = frozenset({"-S", "--split-string"})
ENV_VALUE_OPTIONS = frozenset({"-C", "-u", "--chdir", "--unset"})
MAX_COMMAND_WRAPPER_DEPTH = 4
MAX_COMMAND_INPUT_BYTES = 65_536
MAX_COMMAND_TOKENS = 4_096
MAX_COMMAND_WORK = 262_144
MAX_RAW_JSON_INPUT_BYTES = 65_536
MAX_RAW_JSON_DEPTH = 64
MAX_RAW_JSON_TOKENS = 8_192
MAX_RAW_JSON_STRING_BYTES = 32_768
MAX_RAW_JSON_REPLACEMENTS = 2_048
MAX_RAW_JSON_WORK = 262_144
RAW_JSON_SPAN_PREFIXES = frozenset(" \t\r\n{[:,=()]")
ACTIONS_JOB_LOG_TIMESTAMP_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})[ \t]"
)
JSON_ARRAY_NUMBER_STARTERS = frozenset("0123456789-")
JSON_ARRAY_CONTAINER_STARTERS = frozenset("{[")
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


def _key_identifies_command_evidence(value: object) -> bool:
    """Return whether an exact structured key owns command or argv evidence."""
    normalized = NON_KEY_WORD_RE.sub("_", str(value).lower()).strip("_")
    return normalized in COMMAND_EVIDENCE_KEYS


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
            if (
                key_identifies_credentials
                or _key_identifies_credentials(cleaned_key)
                or key_has_unsafe_controls
            ):
                cleaned[cleaned_key] = REDACTED
            elif _key_identifies_command_evidence(cleaned_key):
                if isinstance(item, str):
                    cleaned[cleaned_key] = _redact_command_text_with_pattern(
                        item,
                        literal_pattern,
                    )
                elif isinstance(item, list) and all(
                    isinstance(argument, str) for argument in item
                ):
                    cleaned[cleaned_key] = _redact_command_argv_with_pattern(
                        item,
                        literal_pattern,
                    )
                else:
                    cleaned[cleaned_key] = _redact_json(
                        item,
                        literal_pattern,
                        redact_literal_keys,
                    )
            else:
                cleaned[cleaned_key] = _redact_json(
                    item,
                    literal_pattern,
                    redact_literal_keys,
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


class _CommandRedactionError(Exception):
    """Signal that bounded command evidence cannot be parsed safely."""


def _command_option_identifies_credentials(argument: str) -> bool:
    """Return whether an argv element expects a separate credential value."""
    if not argument.startswith("-") or "=" in argument:
        return False
    if argument.lower() == "--password-stdin":
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
        and len(command) > 1
        and command[1] == "login"
        and index > 1
    )


def _spend_command_budget(
    budget: dict[str, int],
    *,
    text: str = "",
    tokens: int = 0,
) -> None:
    """Charge UTF-8 scan work and parsed tokens to one root-owned budget."""
    budget["work"] -= len(text.encode("utf-8"))
    budget["tokens"] -= tokens
    if budget["work"] < 0 or budget["tokens"] < 0:
        raise _CommandRedactionError


def _validate_wrapper_operand(text: str, *, shell_operand: bool) -> None:
    """Accept only the documented linear quote grammar for one wrapper operand."""
    quote = ""
    shell_metacharacters = frozenset(";&|<>()*?[]{}")
    for character in text:
        if character in "\r\n\v\f" or character == "\\":
            raise _CommandRedactionError
        if quote:
            if character == quote:
                quote = ""
            elif quote == '"' and character in "`$":
                raise _CommandRedactionError
            continue
        if character in "'\"":
            quote = character
        elif character in "`$#":
            raise _CommandRedactionError
        elif shell_operand and character in shell_metacharacters:
            raise _CommandRedactionError
    if quote:
        raise _CommandRedactionError


def _tokenize_wrapper_operand(
    text: str,
    *,
    shell_operand: bool,
    budget: dict[str, int],
) -> list[str]:
    """Validate and tokenize one nested wrapper operand within the shared budget."""
    _spend_command_budget(budget, text=text)
    _validate_wrapper_operand(text, shell_operand=shell_operand)
    arguments = shlex.split(text, comments=False, posix=True)
    if not arguments:
        raise _CommandRedactionError
    _spend_command_budget(budget, tokens=len(arguments))
    return arguments


def _env_split_operand(command: Sequence[str]) -> tuple[int, str] | None:
    """Locate an exact GNU env split-string operand or report no such wrapper."""
    index = 1
    while index < len(command):
        argument = command[index]
        if argument in ENV_SPLIT_OPTIONS:
            if index + 1 >= len(command) or index + 2 != len(command):
                raise _CommandRedactionError
            return index + 1, ""
        if argument.startswith("--split-string="):
            if index + 1 != len(command) or not argument.partition("=")[2]:
                raise _CommandRedactionError
            return index, "--split-string="
        if argument in ENV_VALUE_OPTIONS:
            if index + 1 >= len(command):
                return None
            index += 2
            continue
        if argument.startswith(("--unset=", "--chdir=")) or re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*=.*",
            argument,
        ):
            index += 1
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return None
    return None


def _shell_command_operand(command: Sequence[str]) -> int | None:
    """Locate a shell command string selected by an exact or combined c option."""
    for index, argument in enumerate(command[1:], start=1):
        if argument == "--":
            return None
        if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", argument) and argument.count("c") == 1:
            if index + 1 >= len(command) or index + 2 != len(command):
                raise _CommandRedactionError
            return index + 1
        if not argument.startswith("-"):
            return None
    return None


def _nested_command_start(arguments: Sequence[str], *, env_operand: bool) -> int:
    """Return the actual program position after bounded assignment/env modifiers."""
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", argument):
            index += 1
            continue
        if env_operand and argument in ENV_VALUE_OPTIONS:
            if index + 1 >= len(arguments):
                return len(arguments)
            index += 2
            continue
        if env_operand and argument.startswith(("--unset=", "--chdir=")):
            index += 1
            continue
        if env_operand and argument == "--":
            return index + 1
        if env_operand and argument.startswith("-"):
            index += 1
            continue
        return index
    return index


def _redact_nested_command(
    operand: str,
    *,
    shell_operand: bool,
    literal_pattern: re.Pattern[str] | None,
    budget: dict[str, int],
    depth: int,
) -> str:
    """Redact one nested command or hide it completely at the depth boundary."""
    if depth >= MAX_COMMAND_WRAPPER_DEPTH:
        return REDACTED
    arguments = _tokenize_wrapper_operand(
        operand,
        shell_operand=shell_operand,
        budget=budget,
    )
    command_start = _nested_command_start(
        arguments,
        env_operand=not shell_operand,
    )
    cleaned = [
        _redact_unstructured(argument, literal_pattern)
        for argument in arguments[:command_start]
    ]
    if command_start < len(arguments):
        cleaned.extend(
            _redact_command_argv(
                arguments[command_start:],
                literal_pattern=literal_pattern,
                budget=budget,
                depth=depth + 1,
            )
        )
    joined = shlex.join(cleaned)
    _spend_command_budget(budget, text=joined)
    return joined


def _command_option_at_index_identifies_credentials(
    command: Sequence[str],
    index: int,
    argument: str,
) -> bool:
    """Apply program-aware exceptions before generic sensitive-option matching."""
    if (
        command
        and _command_program(command[0]) == "env"
        and (
            argument in ENV_VALUE_OPTIONS
            or argument.startswith(("--unset=", "--chdir="))
        )
    ):
        return False
    return _command_option_identifies_credentials(argument)


def _redact_command_argv(
    command: Sequence[str],
    *,
    literal_pattern: re.Pattern[str] | None,
    budget: dict[str, int],
    depth: int,
) -> list[str]:
    """Redact one already-counted argv and its supported nested wrapper operand."""
    replacements: dict[int, str] = {}
    if command:
        program = _command_program(command[0])
        if program == "env":
            split_operand = _env_split_operand(command)
            if split_operand is not None:
                index, prefix = split_operand
                operand = command[index][len(prefix) :] if prefix else command[index]
                replacements[index] = prefix + _redact_nested_command(
                    operand,
                    shell_operand=False,
                    literal_pattern=literal_pattern,
                    budget=budget,
                    depth=depth,
                )
        elif program in COMMAND_WRAPPER_SHELLS:
            index = _shell_command_operand(command)
            if index is not None:
                replacements[index] = _redact_nested_command(
                    command[index],
                    shell_operand=True,
                    literal_pattern=literal_pattern,
                    budget=budget,
                    depth=depth,
                )

    cleaned: list[str] = []
    redact_next = False
    for index, argument in enumerate(command):
        if redact_next:
            cleaned.append(REDACTED)
            redact_next = False
            continue
        argument = replacements.get(index, argument)
        option, separator, _value = argument.partition("=")
        if (
            separator
            and option.startswith("-")
            and (
                option.lower() == "--password-stdin"
                or _command_option_at_index_identifies_credentials(
                    command,
                    index,
                    option,
                )
                or _container_login_password_option(command, index, argument)
            )
        ):
            cleaned.append(f"{option}={REDACTED}")
            continue
        cleaned.append(_redact_unstructured(argument, literal_pattern))
        redact_next = (
            _command_option_at_index_identifies_credentials(
                command,
                index,
                argument,
            )
            or _container_login_password_option(command, index, argument)
        )
    return cleaned


def _redact_command_argv_with_pattern(
    command: Sequence[str],
    literal_pattern: re.Pattern[str] | None,
) -> list[str]:
    """Redact one public argv using an already-compiled literal matcher."""
    arguments = list(command)
    input_text = "\0".join(arguments)
    if len(input_text.encode("utf-8")) > MAX_COMMAND_INPUT_BYTES:
        return [REDACTED]
    budget = {"tokens": MAX_COMMAND_TOKENS, "work": MAX_COMMAND_WORK}
    try:
        _spend_command_budget(budget, text=input_text, tokens=len(arguments))
        return _redact_command_argv(
            arguments,
            literal_pattern=literal_pattern,
            budget=budget,
            depth=0,
        )
    except _CommandRedactionError:
        return [REDACTED]


def redact_command_argv(
    command: Sequence[str],
    *,
    sensitive_values: Sequence[str] = (),
) -> list[str]:
    """Redact argv and bounded supported wrapper operands without changing execution."""
    values = _canonical_sensitive_values(sensitive_values)
    return _redact_command_argv_with_pattern(
        command,
        _compile_literal_pattern(values),
    )


def _redact_command_text_with_pattern(
    command: str,
    literal_pattern: re.Pattern[str] | None,
) -> str:
    """Redact one public command string using an already-compiled matcher."""
    if len(command.encode("utf-8")) > MAX_COMMAND_INPUT_BYTES:
        return REDACTED
    if _contains_unsafe_render_controls(command):
        return REDACTED
    budget = {"tokens": MAX_COMMAND_TOKENS, "work": MAX_COMMAND_WORK}
    try:
        _spend_command_budget(budget, text=command)
    except _CommandRedactionError:
        return REDACTED
    try:
        arguments = shlex.split(command, comments=False, posix=True)
    except ValueError:
        cleaned_command = _redact_unstructured(command, literal_pattern)
        rough_arguments = cleaned_command.split()
        rough_program = _command_program(rough_arguments[0])
        if rough_program == "env" and any(
            argument in ENV_SPLIT_OPTIONS
            or argument.startswith("--split-string=")
            for argument in rough_arguments[1:]
        ):
            return REDACTED
        if rough_program in COMMAND_WRAPPER_SHELLS and any(
            re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", argument)
            and argument.count("c") == 1
            for argument in rough_arguments[1:]
        ):
            return REDACTED
        if any(
            _command_option_identifies_credentials(argument)
            for argument in rough_arguments
        ):
            return REDACTED
        return cleaned_command
    try:
        _spend_command_budget(budget, tokens=len(arguments))
        cleaned = _redact_command_argv(
            arguments,
            literal_pattern=literal_pattern,
            budget=budget,
            depth=0,
        )
        joined = shlex.join(cleaned)
        _spend_command_budget(budget, text=joined)
        return joined
    except _CommandRedactionError:
        return REDACTED


def redact_command_text(
    command: str,
    *,
    sensitive_values: Sequence[str] = (),
) -> str:
    """Redact bounded shell-like evidence without changing the executed command."""
    values = _canonical_sensitive_values(sensitive_values)
    return _redact_command_text_with_pattern(
        command,
        _compile_literal_pattern(values),
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


class _RawJsonError(Exception):
    """Signal malformed or over-budget raw JSON structural evidence."""


def _raw_json_spend(budget: dict[str, int], *, tokens: int = 0, work: int = 0) -> None:
    """Charge one raw JSON token/span operation to its bounded root budget."""
    budget["tokens"] -= tokens
    budget["work"] -= work
    if budget["tokens"] < 0 or budget["work"] < 0:
        raise _RawJsonError


def _skip_actions_job_log_noise(text: str, cursor: int) -> int:
    """Advance over JSON whitespace and line-start RFC 3339 runner timestamps."""
    while cursor < len(text):
        if text[cursor] in " \t\r\n":
            cursor += 1
            continue
        if cursor == 0 or text[cursor - 1] in "\n\r":
            match = ACTIONS_JOB_LOG_TIMESTAMP_RE.match(text, cursor)
            if match is not None:
                cursor = match.end()
                continue
        break
    return cursor


def _raw_json_skip_space(text: str, cursor: int, budget: dict[str, int]) -> int:
    """Advance over JSON whitespace and runner timestamps while charging work."""
    start = cursor
    cursor = _skip_actions_job_log_noise(text, cursor)
    _raw_json_spend(budget, work=cursor - start)
    return cursor


def _is_plausible_json_array_start(text: str, index: int) -> bool:
    """Return whether '[' opens a JSON array rather than a diagnostic label."""
    cursor = _skip_actions_job_log_noise(text, index + 1)
    if cursor >= len(text):
        return False
    character = text[cursor]
    if character == "]":
        return True
    if character == "t":
        return text.startswith("true", cursor)
    if character == "f":
        return text.startswith("false", cursor)
    if character == "n":
        return text.startswith("null", cursor)
    return character in JSON_ARRAY_NUMBER_STARTERS | JSON_ARRAY_CONTAINER_STARTERS


def _raw_json_string(text: str, cursor: int, budget: dict[str, int]) -> int:
    """Return the exclusive end of one validated, bounded JSON string token."""
    start = cursor
    cursor += 1
    escaped = False
    while cursor < len(text):
        character = text[cursor]
        cursor += 1
        if escaped:
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == '"':
            token = text[start:cursor]
            if len(token.encode("utf-8")) > MAX_RAW_JSON_STRING_BYTES:
                raise _RawJsonError
            try:
                json.loads(token)
            except (ValueError, RecursionError) as error:
                raise _RawJsonError from error
            _raw_json_spend(budget, tokens=1, work=cursor - start)
            return cursor
        elif ord(character) < 0x20:
            raise _RawJsonError
    raise _RawJsonError


def _raw_json_scalar(text: str, cursor: int, budget: dict[str, int]) -> tuple[int, str]:
    """Return the exclusive end and category of one non-container JSON scalar."""
    if text[cursor] == '"':
        return _raw_json_string(text, cursor, budget), "string"
    for literal, category in (("true", "boolean"), ("false", "boolean"), ("null", "null")):
        if text.startswith(literal, cursor):
            _raw_json_spend(budget, tokens=1, work=len(literal))
            return cursor + len(literal), category
    match = re.match(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", text[cursor:])
    if match is None:
        raise _RawJsonError
    token = match.group(0)
    _raw_json_spend(budget, tokens=1, work=len(token))
    return cursor + len(token), ("float" if any(mark in token for mark in ".eE") else "integer")


def _raw_json_start_value(
    text: str,
    cursor: int,
    depth: int,
    budget: dict[str, int],
) -> tuple[dict[str, Any], int, bool]:
    """Start one bounded value and report whether it opened a container."""
    if depth > MAX_RAW_JSON_DEPTH:
        raise _RawJsonError
    cursor = _raw_json_skip_space(text, cursor, budget)
    if cursor >= len(text):
        raise _RawJsonError
    start = cursor
    opener = text[cursor]
    if opener not in "{[":
        end, category = _raw_json_scalar(text, cursor, budget)
        return {"kind": category, "start": start, "end": end, "children": []}, end, False
    _raw_json_spend(budget, tokens=1, work=1)
    return (
        {
            "kind": "object" if opener == "{" else "array",
            "start": start,
            "children": [],
        },
        cursor + 1,
        True,
    )


def _raw_json_attach_child(
    frame: dict[str, Any],
    child: dict[str, Any],
) -> None:
    """Attach pending object-key metadata to one parsed child node."""
    key = frame.pop("key", None)
    if key is not None:
        child["key"] = key
        child["key_start"] = frame.pop("key_start")
        child["key_end"] = frame.pop("key_end")
    child["sensitive"] = key is not None and (
        _key_identifies_credentials(key)
        or (isinstance(key, str) and _contains_unsafe_render_controls(key))
    )
    child["command_evidence"] = key is not None and _key_identifies_command_evidence(key)
    frame["node"]["children"].append(child)


def _raw_json_parse_value(
    text: str,
    cursor: int,
    depth: int,
    budget: dict[str, int],
) -> tuple[dict[str, Any], int]:
    """Iteratively parse one bounded JSON value into source-span nodes."""
    root, cursor, _ = _raw_json_start_value(text, cursor, depth, budget)
    stack: list[dict[str, Any]] = [
        {
            "node": root,
            "depth": depth,
            "state": "key_or_end" if root["kind"] == "object" else "value_or_end",
        }
    ]
    while stack:
        frame = stack[-1]
        node = frame["node"]
        kind = node["kind"]
        closer = "}" if kind == "object" else "]"
        state = frame["state"]
        cursor = _raw_json_skip_space(text, cursor, budget)

        if state in {"key_or_end", "value_or_end"} and (
            cursor < len(text) and text[cursor] == closer
        ):
            _raw_json_spend(budget, tokens=1, work=1)
            cursor += 1
            node["end"] = cursor
            stack.pop()
            continue

        if state in {"key_or_end", "key"}:
            if cursor >= len(text) or text[cursor] != '"':
                raise _RawJsonError
            key_start = cursor
            key_end = _raw_json_string(text, cursor, budget)
            key = json.loads(text[cursor:key_end])
            cursor = _raw_json_skip_space(text, key_end, budget)
            if cursor >= len(text) or text[cursor] != ":":
                raise _RawJsonError
            _raw_json_spend(budget, tokens=1, work=1)
            frame.update(
                state="value",
                key=key,
                key_start=key_start,
                key_end=key_end,
            )
            cursor += 1
            continue

        if state in {"value_or_end", "value"}:
            child, cursor, child_opened = _raw_json_start_value(
                text,
                cursor,
                frame["depth"] + 1,
                budget,
            )
            _raw_json_attach_child(frame, child)
            frame["state"] = "comma_or_end"
            if child_opened:
                stack.append(
                    {
                        "node": child,
                        "depth": frame["depth"] + 1,
                        "state": (
                            "key_or_end" if child["kind"] == "object" else "value_or_end"
                        ),
                    }
                )
            continue

        if state != "comma_or_end" or cursor >= len(text):
            raise _RawJsonError
        if text[cursor] == closer:
            _raw_json_spend(budget, tokens=1, work=1)
            cursor += 1
            node["end"] = cursor
            stack.pop()
            continue
        if text[cursor] != ",":
            raise _RawJsonError
        _raw_json_spend(budget, tokens=1, work=1)
        frame["state"] = "key" if kind == "object" else "value"
        cursor += 1
    return root, cursor


def _raw_json_add_replacement(
    replacements: list[tuple[int, int, str]],
    start: int,
    end: int,
    replacement: str,
) -> None:
    """Append one span replacement while enforcing the root replacement limit."""
    replacements.append((start, end, replacement))
    if len(replacements) > MAX_RAW_JSON_REPLACEMENTS:
        raise _RawJsonError


def _raw_json_leaf_replacements(
    node: dict[str, Any],
    *,
    text: str,
    literal_pattern: re.Pattern[str] | None,
    force: bool,
    replacements: list[tuple[int, int, str]],
) -> None:
    """Iteratively collect layout-preserving replacements from a span tree."""
    pending: list[tuple[dict[str, Any], bool]] = [(node, force)]
    while pending:
        current, inherited_force = pending.pop()
        if "key_start" in current:
            key = str(current["key"])
            cleaned_key = str(current.get("rendered_key", key))
            if cleaned_key != key:
                _raw_json_add_replacement(
                    replacements,
                    current["key_start"],
                    current["key_end"],
                    json.dumps(cleaned_key, ensure_ascii=False),
                )
        current_force = inherited_force or bool(current.get("sensitive"))
        kind = current["kind"]
        if current.get("command_evidence") and kind == "string":
            decoded = json.loads(text[current["start"] : current["end"]])
            cleaned_command = _redact_command_text_with_pattern(decoded, literal_pattern)
            if cleaned_command != decoded:
                _raw_json_add_replacement(
                    replacements,
                    current["start"],
                    current["end"],
                    json.dumps(cleaned_command, ensure_ascii=False),
                )
            continue
        if current.get("command_evidence") and kind == "array" and all(
            child["kind"] == "string" for child in current["children"]
        ):
            decoded_arguments = [
                json.loads(text[child["start"] : child["end"]])
                for child in current["children"]
            ]
            cleaned_arguments = _redact_command_argv_with_pattern(
                decoded_arguments,
                literal_pattern,
            )
            if len(cleaned_arguments) != len(current["children"]):
                cleaned_arguments = [REDACTED] * len(current["children"])
            for child, original, cleaned in zip(
                current["children"],
                decoded_arguments,
                cleaned_arguments,
                strict=True,
            ):
                if cleaned != original:
                    _raw_json_add_replacement(
                        replacements,
                        child["start"],
                        child["end"],
                        json.dumps(cleaned, ensure_ascii=False),
                    )
            continue
        if kind == "object":
            used_keys: set[str] = set()
            used_sources: dict[str, set[str]] = {}
            collision_counts: dict[str, int] = {}
            for child in current["children"]:
                key = str(child["key"])
                cleaned_key = _redact_unstructured(key, literal_pattern)
                if cleaned_key in used_keys and key not in used_sources.get(cleaned_key, set()):
                    collision_index = collision_counts.get(cleaned_key, 2)
                    while f"{cleaned_key}#{collision_index}" in used_keys:
                        collision_index += 1
                    collision_counts[cleaned_key] = collision_index + 1
                    cleaned_key = f"{cleaned_key}#{collision_index}"
                child["rendered_key"] = cleaned_key
                used_keys.add(cleaned_key)
                used_sources.setdefault(cleaned_key, set()).add(key)
        if kind in {"object", "array"}:
            pending.extend(
                (child, current_force) for child in reversed(current["children"])
            )
            continue
        if not current_force and kind == "string":
            decoded = json.loads(text[current["start"] : current["end"]])
            cleaned = _redact_unstructured(decoded, literal_pattern)
            if cleaned != decoded:
                _raw_json_add_replacement(
                    replacements,
                    current["start"],
                    current["end"],
                    json.dumps(cleaned, ensure_ascii=False),
                )
        if not current_force or kind == "null":
            continue
        replacement = {
            "string": json.dumps(REDACTED),
            "integer": "0",
            "float": "0.0",
            "boolean": "false",
        }[kind]
        _raw_json_add_replacement(
            replacements,
            current["start"],
            current["end"],
            replacement,
        )


def _looks_like_sensitive_json_candidate(text: str) -> bool:
    """Return whether a malformed structural suffix names a sensitive JSON key."""
    for match in re.finditer(r'"(?:\\.|[^"\\])*"\s*:', text):
        try:
            key = json.loads(match.group(0).rsplit(":", 1)[0].rstrip())
        except (ValueError, RecursionError):
            continue
        if _key_identifies_credentials(key):
            return True
    return False


def _is_plausible_raw_json_start(text: str, index: int) -> bool:
    """Return whether a brace or bracket can start a top-level JSON span."""
    if index > 0 and text[index - 1] not in RAW_JSON_SPAN_PREFIXES:
        return False
    if text[index] == "[":
        return _is_plausible_json_array_start(text, index)
    return True


def _next_plausible_raw_json_start(text: str, index: int) -> int:
    """Return the next plausible JSON opener after index, or the text length."""
    cursor = index
    while cursor < len(text):
        if text[cursor] in "{[" and _is_plausible_raw_json_start(text, cursor):
            return cursor
        cursor += 1
    return len(text)


def _redact_plain_json_gap(
    text: str,
    literal_pattern: re.Pattern[str] | None,
) -> str:
    """Redact non-JSON slices without invoking structural line normalization."""
    output: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        separator = LINE_SEPARATOR_END_RE.search(raw_line)
        line_end = separator.start() if separator is not None else len(raw_line)
        output.append(_redact_unstructured(raw_line[:line_end], literal_pattern))
        output.append(raw_line[line_end:])
    return "".join(output)


def _redact_raw_json_spans(
    text: str,
    literal_pattern: re.Pattern[str] | None,
) -> tuple[str, bool]:
    """Rewrite complete bounded JSON spans before any line-oriented processing."""
    if len(text.encode("utf-8")) > MAX_RAW_JSON_INPUT_BYTES:
        if _looks_like_sensitive_json_candidate(text):
            return REDACTED, True
        return text, False
    replacements: list[tuple[int, int, str]] = []
    spans: list[tuple[int, int]] = []
    cursor = 0
    parsed = False
    budget = {"tokens": MAX_RAW_JSON_TOKENS, "work": MAX_RAW_JSON_WORK}
    while cursor < len(text):
        if text[cursor] not in "{[" or not _is_plausible_raw_json_start(text, cursor):
            cursor += 1
            continue
        start = cursor
        try:
            node, end = _raw_json_parse_value(text, start, 0, budget)
        except _RawJsonError:
            window_end = _next_plausible_raw_json_start(text, start + 1)
            if _looks_like_sensitive_json_candidate(text[start:window_end]):
                return REDACTED, True
            cursor += 1
            continue
        parsed = True
        spans.append((start, end))
        try:
            _raw_json_leaf_replacements(
                node,
                text=text,
                literal_pattern=literal_pattern,
                force=False,
                replacements=replacements,
            )
        except _RawJsonError:
            return REDACTED, True
        cursor = end
    if not parsed:
        return text, False
    replacements.sort()
    output: list[str] = []
    gap_start = 0
    replacement_index = 0
    for span_start, span_end in spans:
        output.append(_redact_plain_json_gap(text[gap_start:span_start], literal_pattern))
        span_cursor = span_start
        while replacement_index < len(replacements):
            start, end, replacement = replacements[replacement_index]
            if start >= span_end:
                break
            output.append(text[span_cursor:start])
            output.append(replacement)
            span_cursor = end
            replacement_index += 1
        output.append(text[span_cursor:span_end])
        gap_start = span_end
    output.append(_redact_plain_json_gap(text[gap_start:], literal_pattern))
    return "".join(output), True


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
    text, raw_json_processed = _redact_raw_json_spans(
        text,
        unstructured_literal_pattern,
    )
    if raw_json_processed:
        return text
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
