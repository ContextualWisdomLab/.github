#!/usr/bin/env python3
"""Strict primitives for independent OpenCode review decisions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
VALID_SEMANTIC_STATUSES = {"complete", "unavailable", "failed"}
VALID_SEVERITIES = {"critical", "high", "medium", "low"}
VALID_EVIDENCE_STATES = {
    "success",
    "failure",
    "pending",
    "queued",
    "absent",
    "cancelled",
    "skipped",
    "neutral",
}
HARD_BLOCKING_STATES = {"failure", "cancelled", "skipped", "neutral"}
UNKNOWN_STATES = {"pending", "queued", "absent"}


class DecisionValidationError(ValueError):
    """Signal malformed or internally inconsistent decision evidence."""


def reject(message: str) -> None:
    """Raise one stable decision validation error."""
    raise DecisionValidationError(message)


def object_value(value: Any, path: str) -> Mapping[str, Any]:
    """Return a JSON object or reject its shape."""
    if not isinstance(value, Mapping):
        reject(f"{path} must be an object")
    return value


def array_value(value: Any, path: str) -> list[Any]:
    """Return a JSON array or reject its shape."""
    if not isinstance(value, list):
        reject(f"{path} must be an array")
    return value


def require_exact_fields(
    value: Mapping[str, Any], path: str, allowed_fields: set[str]
) -> None:
    """Reject unreviewed extension fields at one governed schema layer."""
    unknown = sorted(set(value) - allowed_fields)
    if unknown:
        reject(f"{path} has unknown fields: {', '.join(unknown)}")


def text_value(value: Any, path: str) -> str:
    """Return stripped non-empty text or reject it."""
    if not isinstance(value, str) or not value.strip():
        reject(f"{path} must be non-empty text")
    return value.strip()


def bool_value(value: Any, path: str) -> bool:
    """Return an actual Boolean rather than an integer lookalike."""
    if not isinstance(value, bool):
        reject(f"{path} must be boolean")
    return value


def positive_int_value(value: Any, path: str) -> int:
    """Return a strictly positive integer without Boolean coercion."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        reject(f"{path} must be a positive integer")
    return value


def commit_sha_value(value: Any, path: str) -> str:
    """Return one full lowercase commit SHA."""
    result = text_value(value, path)
    if not COMMIT_SHA_RE.fullmatch(result):
        reject(f"{path} must be a 40-character lowercase commit SHA")
    return result


def optional_commit_sha_value(value: Any, path: str) -> str | None:
    """Return ``None`` or one full lowercase commit SHA."""
    return None if value is None else commit_sha_value(value, path)


def enum_value(value: Any, path: str, allowed: set[str]) -> str:
    """Return a normalized enumerated value or reject it."""
    result = text_value(value, path).casefold()
    if result not in allowed:
        reject(f"{path} is invalid: {result!r}")
    return result


def source_path_value(value: Any, path: str) -> str:
    """Return a safe repository-relative POSIX source path."""
    result = text_value(value, path)
    pure = PurePosixPath(result)
    if (
        pure.is_absolute()
        or "\\" in result
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        reject(f"{path} must be a safe relative source path")
    return pure.as_posix()


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for content-addressed receipts."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """Return the canonical SHA-256 digest for a JSON-compatible value."""
    encoded = canonical_json(value).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting duplicate member names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            reject(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value: str) -> None:
    """Reject non-finite constants accepted by Python's permissive JSON parser."""
    reject(f"non-finite JSON number: {value}")


def load_json(path: Path) -> Any:
    """Load strict UTF-8 JSON with bounded stable validation errors."""
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=strict_pairs,
            parse_constant=reject_constant,
        )
    except (OSError, json.JSONDecodeError) as error:
        reject(f"cannot load decision evidence: {error}")


def write_text(path: Path, content: str) -> None:
    """Atomically replace one UTF-8 output after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)
