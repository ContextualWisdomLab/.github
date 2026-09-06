#!/usr/bin/env python3
"""Resolve a repository-owned Rust line-coverage baseline from Cargo metadata."""

from __future__ import annotations

import argparse
import fnmatch
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


def _relative_posix_path(path: Path, base: Path) -> str | None:
    """Return ``path`` relative to ``base`` as a POSIX string, or None if unrelated."""
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return None


def _workspace_excludes_package(
    workspace_dir: Path, package_dir: Path, workspace_document: dict[str, Any]
) -> bool:
    """Return whether a workspace's ``exclude`` patterns cover the package directory.

    Cargo's own automatic workspace-root discovery walks upward from a
    package's manifest and skips an ancestor workspace that excludes it,
    continuing the search further out rather than treating the excluded
    workspace as authoritative. Mirroring that here keeps an excluded (or
    otherwise independent) package from inheriting a coverage baseline that
    was never configured for it.
    """
    workspace_table = workspace_document.get("workspace")
    if not isinstance(workspace_table, dict):
        return False
    excludes = workspace_table.get("exclude")
    if not isinstance(excludes, list):
        return False
    relative = _relative_posix_path(package_dir, workspace_dir)
    if relative is None:
        return False
    for pattern in excludes:
        if not isinstance(pattern, str):
            continue
        normalized_pattern = pattern.rstrip("/")
        if relative == normalized_pattern or fnmatch.fnmatch(relative, normalized_pattern):
            return True
        if relative.startswith(f"{normalized_pattern}/"):
            return True
    return False


def read_minimum_lines(manifest: Path) -> float | None:
    """Read a package baseline, falling back to its nearest workspace baseline."""
    manifest = manifest.resolve()
    document = tomllib.loads(manifest.read_text(encoding="utf-8"))
    threshold = resolve_minimum_lines(document)
    if threshold is not None:
        return threshold

    package_dir = manifest.parent
    for parent in manifest.parents:
        workspace_manifest = parent / "Cargo.toml"
        if not workspace_manifest.is_file():
            continue
        workspace_document = tomllib.loads(workspace_manifest.read_text(encoding="utf-8"))
        if "workspace" not in workspace_document:
            continue
        if _workspace_excludes_package(parent, package_dir, workspace_document):
            # This ancestor's workspace explicitly excludes the package, so
            # it is not this package's workspace root. Keep walking further
            # out for an unrelated ancestor workspace that might still
            # legitimately claim it, matching Cargo's own root-discovery
            # rule for excluded members.
            continue
        # This is the package's actual (nearest, non-excluding) Cargo
        # workspace root -- whether the sole enclosing workspace or a
        # nested, independent one. Stop here even when it configures no
        # baseline: crossing this boundary to search an even-more-outer,
        # unrelated workspace would attribute a threshold that was never
        # configured for this package's own workspace.
        workspace_value = _nested_value(workspace_document, METADATA_PATHS[1])
        if workspace_value is not None:
            return _validate_minimum_lines(METADATA_PATHS[1], workspace_value)
        return None
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
