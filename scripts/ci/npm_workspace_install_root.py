#!/usr/bin/env python3
"""Resolve the trusted npm install root for a JavaScript package.

A changed file can belong to a nested npm workspace package even though the
only dependency lock lives at the workspace root. Coverage must install from
that lock owner rather than treating the nested package as an independent
unlocked project. This resolver reads data only, rejects symlink/path escapes,
and requires both the root workspace declaration and lockfile package map to
contain the requested package.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
from pathlib import Path, PurePosixPath
from typing import Any

NPM_LOCK_NAMES = ("npm-shrinkwrap.json", "package-lock.json")


def _regular_file(path: Path, description: str) -> None:
    """Require one existing regular non-symlink file."""
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{description} must be a regular non-symlink file: {path}")


def _load_object(path: Path, description: str) -> dict[str, Any]:
    """Load one JSON object from a regular non-symlink file."""
    _regular_file(path, description)
    try:
        payload: Any = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{description} is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{description} must be a JSON object")
    return payload


def _workspace_patterns(package_data: dict[str, Any]) -> list[str]:
    """Return validated npm workspace patterns from a package manifest."""
    workspaces = package_data.get("workspaces")
    if isinstance(workspaces, list):
        raw_patterns = workspaces
    elif isinstance(workspaces, dict):
        raw_patterns = workspaces.get("packages")
    else:
        raw_patterns = None
    if not isinstance(raw_patterns, list):
        return []

    patterns: list[str] = []
    for raw_pattern in raw_patterns:
        if not isinstance(raw_pattern, str) or not raw_pattern:
            raise ValueError("npm workspace patterns must be non-empty strings")
        if "\\" in raw_pattern:
            raise ValueError(f"unsafe npm workspace pattern: {raw_pattern!r}")
        candidate = PurePosixPath(raw_pattern)
        if (
            candidate.is_absolute()
            or ".." in candidate.parts
            or "node_modules" in candidate.parts
        ):
            raise ValueError(f"unsafe npm workspace pattern: {raw_pattern!r}")
        patterns.append(raw_pattern.rstrip("/"))
    return patterns


def _is_declared_workspace(relative_package: str, patterns: list[str]) -> bool:
    """Return whether a repository-relative package matches a workspace pattern."""
    return any(
        fnmatch.fnmatchcase(relative_package, pattern)
        or fnmatch.fnmatchcase(f"{relative_package}/", f"{pattern.rstrip('/')}/")
        for pattern in patterns
    )


def resolve_install_root(repo_root: Path, package_dir: Path) -> str:
    """Return the repository-relative npm lock owner for ``package_dir``.

    ``.`` denotes the repository root. Nested packages are accepted only when
    an ancestor package manifest declares them as a workspace and the ancestor
    lockfile's ``packages`` map contains their exact relative path.
    """
    if repo_root.is_symlink():
        raise ValueError("repository root must be a real non-symlink directory")
    if package_dir.is_symlink():
        raise ValueError("npm package directory must be a real non-symlink directory")
    root = repo_root.resolve(strict=True)
    package = package_dir.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("repository root must be a real non-symlink directory")
    try:
        package.relative_to(root)
    except ValueError as exc:
        raise ValueError("npm package directory escaped the validated repository") from exc
    if not package.is_dir() or package.is_symlink():
        raise ValueError("npm package directory must be a real non-symlink directory")
    _regular_file(package / "package.json", "npm package manifest")

    candidate = package
    while True:
        lock = next(
            (
                candidate / name
                for name in NPM_LOCK_NAMES
                if (candidate / name).is_file() and not (candidate / name).is_symlink()
            ),
            None,
        )
        if lock is not None:
            _regular_file(candidate / "package.json", "npm lock-owner manifest")
            if candidate != package:
                relative_package = package.relative_to(candidate).as_posix()
                package_data = _load_object(
                    candidate / "package.json", "npm lock-owner manifest"
                )
                patterns = _workspace_patterns(package_data)
                if not _is_declared_workspace(relative_package, patterns):
                    raise ValueError(
                        f"npm package {relative_package!r} is not declared by the ancestor workspace"
                    )
                lock_data = _load_object(lock, "npm lockfile")
                packages = lock_data.get("packages")
                if not isinstance(packages, dict) or not isinstance(
                    packages.get(relative_package), dict
                ):
                    raise ValueError(
                        f"npm lockfile does not contain workspace package {relative_package!r}"
                    )
            relative_root = candidate.relative_to(root).as_posix()
            return relative_root or "."

        if candidate == root:
            break
        candidate = candidate.parent

    raise ValueError(
        "no regular package-lock.json or npm-shrinkwrap.json owns the npm package"
    )


def main() -> int:
    """Resolve and print one validated npm install root."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        print(resolve_install_root(args.repo_root, args.package_dir))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
