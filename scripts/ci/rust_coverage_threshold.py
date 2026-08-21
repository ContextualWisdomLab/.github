#!/usr/bin/env python3
"""Resolve a repository-owned Rust line-coverage baseline from Cargo metadata."""

from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
from typing import Any

METADATA_PATHS = (
    "package.metadata.opencode.coverage.minimum_lines",
    "workspace.metadata.opencode.coverage.minimum_lines",
)


def _nested_value(document: dict[str, Any], path: str) -> Any:
    """Return a dotted TOML value, or None when any segment is absent."""
    value: Any = document
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def resolve_minimum_lines(document: dict[str, Any]) -> float | None:
    """Return package or virtual-workspace coverage metadata after validation."""
    value = None
    selected_path = None
    for path in METADATA_PATHS:
        candidate = _nested_value(document, path)
        if candidate is not None:
            value = candidate
            selected_path = path
            break
    if selected_path is None:
        return None
    return _validate_minimum_lines(selected_path, value)


def _validate_minimum_lines(path: str, value: Any) -> float:
    """Validate one repository-owned coverage baseline and normalize it."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a number from 0 to 100")
    threshold = float(value)
    if not 0 <= threshold <= 100:
        raise ValueError(f"{path} must be between 0 and 100")
    return threshold


def read_minimum_lines(manifest: Path) -> float | None:
    """Read a package baseline, falling back to its nearest workspace baseline."""
    manifest = manifest.resolve()
    document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    threshold = resolve_minimum_lines(document)
    if threshold is not None:
        return threshold

    for parent in manifest.parents:
        workspace_manifest = parent / "Cargo.toml"
        if not workspace_manifest.is_file():
            continue
        workspace_document = tomllib.loads(workspace_manifest.read_text(encoding="utf-8"))
        if "workspace" not in workspace_document:
            continue
        workspace_value = _nested_value(workspace_document, METADATA_PATHS[1])
        if workspace_value is not None:
            return _validate_minimum_lines(METADATA_PATHS[1], workspace_value)
    return None


def main() -> int:
    """Print the normalized threshold when configured; print nothing otherwise."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        threshold = read_minimum_lines(args.manifest)
    except (OSError, tomllib.TOMLDecodeError, ValueError) as exc:
        parser.error(str(exc))
    if threshold is not None:
        print(f"{threshold:g}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
