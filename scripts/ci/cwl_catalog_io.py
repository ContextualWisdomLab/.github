"""Strict bounded filesystem and JSON handling for the CWL catalogue."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

if __package__:  # pragma: no cover - exercised by the module CLI subprocess
    from .cwl_catalog_contract import (
        MAX_COLLECTION_ITEMS,
        MAX_DEPTH,
        MAX_FILE_BYTES,
        MAX_STRING_LENGTH,
        CatalogValidationError,
    )
else:
    from cwl_catalog_contract import (
        MAX_COLLECTION_ITEMS,
        MAX_DEPTH,
        MAX_FILE_BYTES,
        MAX_STRING_LENGTH,
        CatalogValidationError,
    )


def _reject_constant(value: str) -> None:
    """Reject non-finite JSON constants such as NaN and Infinity."""

    raise CatalogValidationError(f"non-finite JSON value is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting duplicate property names."""

    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise CatalogValidationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> object:
    """Load strict, bounded UTF-8 JSON from a regular non-symlink file."""

    if path.is_symlink():
        raise CatalogValidationError(f"catalogue path must not be a symbolic link: {path}")
    if not path.is_file():
        raise CatalogValidationError(f"catalogue path must be a regular file: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise CatalogValidationError(f"catalogue exceeds the {MAX_FILE_BYTES}-byte input limit")
    try:
        text = path.read_bytes().decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise CatalogValidationError("catalogue must be strict UTF-8") from error
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except CatalogValidationError:
        raise
    except json.JSONDecodeError as error:
        raise CatalogValidationError("catalogue must contain valid JSON") from error


def validate_bounded_value(value: object, depth: int = 0) -> None:
    """Reject recursively excessive depth, collection cardinality, and strings."""

    if depth > MAX_DEPTH:
        raise CatalogValidationError("catalogue exceeds the maximum depth")
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            raise CatalogValidationError("catalogue string limit exceeded")
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise CatalogValidationError("catalogue collection limit exceeded")
        for item in value:
            validate_bounded_value(item, depth + 1)
    elif isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise CatalogValidationError("catalogue collection limit exceeded")
        for key, item in value.items():
            validate_bounded_value(key, depth + 1)
            validate_bounded_value(item, depth + 1)


def resolve_manifest_path(catalog_path: Path, relative_path: str) -> Path:
    """Resolve a manifest below the catalogue directory without symlink escape."""

    root = catalog_path.parent.resolve()
    lexical = catalog_path.parent / relative_path
    current = catalog_path.parent
    for part in Path(relative_path).parts:
        current = current / part
        if current.is_symlink():
            raise CatalogValidationError("service manifest path must not traverse a symbolic link")
    candidate = lexical.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise CatalogValidationError("service manifest path escapes the catalogue directory") from error
    return candidate
