#!/usr/bin/env python3
"""Strict primitive validators for blinded code-review gold evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
VALID_SEVERITIES = {"critical", "high", "medium", "low"}


class AdjudicationError(ValueError):
    """Signal malformed, incomplete, or internally inconsistent gold evidence."""


def reject(message: str) -> None:
    """Raise one stable adjudication validation error."""
    raise AdjudicationError(message)


def object_value(value: Any, path: str) -> Mapping[str, Any]:
    """Return a JSON object or reject one schema-shape mismatch."""
    if not isinstance(value, Mapping):
        reject(f"{path} must be an object")
    return value


def array_value(value: Any, path: str) -> list[Any]:
    """Return a JSON array or reject one schema-shape mismatch."""
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


def optional_text(value: Any, path: str) -> str | None:
    """Return ``None`` or stripped non-empty text without scalar coercion."""
    return None if value is None else text_value(value, path)


def bool_value(value: Any, path: str) -> bool:
    """Return an actual Boolean rather than an integer lookalike."""
    if not isinstance(value, bool):
        reject(f"{path} must be boolean")
    return value


def count_value(value: Any, path: str, *, positive: bool = False) -> int:
    """Return a non-negative or positive integer without Boolean coercion."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        reject(f"{path} must be a non-negative integer")
    if positive and value == 0:
        reject(f"{path} must be a positive integer")
    return value


def optional_positive_count(value: Any, path: str) -> int | None:
    """Return ``None`` or one strictly positive integer."""
    return None if value is None else count_value(value, path, positive=True)


def commit_sha_value(value: Any, path: str) -> str:
    """Return one lowercase full commit SHA."""
    result = text_value(value, path)
    if not COMMIT_SHA_RE.fullmatch(result):
        reject(f"{path} must be a 40-character lowercase commit SHA")
    return result


def digest_value(value: Any, path: str) -> str:
    """Return one canonical SHA-256 evidence digest."""
    result = text_value(value, path)
    if not DIGEST_RE.fullmatch(result):
        reject(f"{path} must use sha256:<64 lowercase hex characters>")
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


def unique_text_values(value: Any, path: str) -> list[str]:
    """Return unique non-empty identifiers while preserving declaration order."""
    output: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(array_value(value, path)):
        identifier = text_value(item, f"{path}[{index}]")
        if identifier in seen:
            reject(f"{path} duplicates {identifier!r}")
        seen.add(identifier)
        output.append(identifier)
    return output


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for content-addressed evidence receipts."""
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    )


def content_digest(value: Any) -> str:
    """Return a canonical SHA-256 digest for a JSON-compatible value."""
    return f"sha256:{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()}"



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


