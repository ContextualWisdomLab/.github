"""Strict deterministic primitives shared by the OpenCode shadow tools."""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")


def canonical_json(value: Any) -> str:
    """Serialize a value to the repository's stable JSON representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest_bytes(value: bytes) -> str:
    """Return a labelled SHA-256 digest for bytes."""
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def digest_json(value: Any) -> str:
    """Return a labelled SHA-256 digest for canonical JSON."""
    return digest_bytes(canonical_json(value).encode("utf-8"))


def _duplicate_key(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build an object while rejecting ambiguous duplicate JSON keys."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(value: str) -> NoReturn:
    """Reject a non-standard non-finite JSON numeric literal."""
    raise ValueError(f"non-finite JSON number: {value}")


def strict_load_json(path: Path, error_type: type[Exception]) -> Any:
    """Load UTF-8 JSON while rejecting duplicate keys and non-finite numbers."""
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_duplicate_key,
            parse_constant=_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise error_type(str(error)) from error


def atomic_write_json(path: Path, value: Any) -> None:
    """Atomically replace a UTF-8 JSON output without leaving a stable temp file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(canonical_json(value) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def require_object(value: Any, label: str, error_type: type[Exception]) -> dict[str, Any]:
    """Return a JSON object or raise the caller's validation error."""
    if not isinstance(value, dict):
        raise error_type(f"{label} must be an object")
    return value


def require_fields(
    value: dict[str, Any], allowed: set[str], label: str, error_type: type[Exception]
) -> None:
    """Require an exact, non-extensible object field set."""
    unknown = set(value) - allowed
    missing = allowed - set(value)
    if unknown:
        raise error_type(f"{label} has unknown fields: {sorted(unknown)}")
    if missing:
        raise error_type(f"{label} is missing fields: {sorted(missing)}")


def require_integer(value: Any, label: str, error_type: type[Exception], *, minimum: int = 0) -> int:
    """Require a real integer at or above a lower bound; booleans are rejected."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise error_type(f"{label} must be an integer")
    if value < minimum:
        raise error_type(f"{label} must be at least {minimum}")
    return value


def require_string(value: Any, label: str, error_type: type[Exception]) -> str:
    """Require a non-empty string."""
    if not isinstance(value, str) or not value:
        raise error_type(f"{label} must be a non-empty string")
    return value


def require_sha256(value: Any, label: str, error_type: type[Exception]) -> str:
    """Require a lowercase labelled SHA-256 digest."""
    text = require_string(value, label, error_type)
    if not SHA256_RE.fullmatch(text):
        raise error_type(f"{label} must be a sha256 digest")
    return text


def require_commit(value: Any, label: str, error_type: type[Exception]) -> str:
    """Require a full lowercase hexadecimal commit SHA."""
    text = require_string(value, label, error_type)
    if not COMMIT_RE.fullmatch(text):
        raise error_type(f"{label} must be a full commit SHA")
    return text


def require_relative_path(value: Any, label: str, error_type: type[Exception]) -> str:
    """Require a normalized relative POSIX source path."""
    text = require_string(value, label, error_type)
    parsed = PurePosixPath(text)
    if parsed.is_absolute() or ".." in parsed.parts or text in {".", ""} or "\\" in text:
        raise error_type(f"{label} must be a relative source path")
    return text
