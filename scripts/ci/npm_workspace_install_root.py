#!/usr/bin/env python3
"""Resolve a trusted npm install root for a selected JavaScript package.

Coverage may select a nested npm workspace package while the only dependency
lock lives at an ancestor workspace root. This resolver establishes ownership
from regular Git blobs at the live-validated head revision, verifies the live
worktree still matches that head, and returns the nearest ancestor whose npm
workspace declaration and authoritative lockfile both cover the package.
The central workflow separately authenticates the returned lock against its
base-or-head materialization receipt before running offline dependency install.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

NPM_LOCK_NAMES = ("npm-shrinkwrap.json", "package-lock.json")
SUPPORTED_LOCKFILE_VERSIONS = frozenset({2, 3})
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_BRACKET_CLASS_RE = re.compile(r"\[(?:!|\^)?[^\[\]/]+\]")


class ResolutionError(ValueError):
    """Raised when an npm install root cannot be proven safe and authoritative."""


def _git(repo_root: Path, *args: str) -> bytes:
    """Run one read-only Git command and return its stdout bytes."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ResolutionError(f"git {args[0]} failed: {stderr or 'unknown error'}")
    return completed.stdout


def _validate_revision(repo_root: Path, revision: str, description: str) -> None:
    """Require one exact commit SHA that exists in the validated repository."""
    if not SHA_RE.fullmatch(revision):
        raise ResolutionError(f"{description} must be exactly 40 hexadecimal characters")
    _git(repo_root, "cat-file", "-e", f"{revision}^{{commit}}")


def _relative_path(root: Path, path: Path, description: str) -> PurePosixPath:
    """Return a safe repository-relative path with no symlinked component."""
    absolute = Path(os.path.abspath(path))
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise ResolutionError(f"{description} escaped the validated repository") from exc

    current = root
    for component in relative.parts:
        current /= component
        if current.is_symlink():
            raise ResolutionError(f"{description} must not traverse a symlink: {current}")
    try:
        absolute.resolve(strict=True)
    except OSError as exc:
        raise ResolutionError(f"{description} does not exist: {path}") from exc
    return PurePosixPath(relative.as_posix())


def _tree_blob(
    repo_root: Path,
    revision: str,
    relative_path: PurePosixPath,
    description: str,
) -> str | None:
    """Return one regular-file blob SHA, or ``None`` when the path is absent."""
    path_text = relative_path.as_posix()
    output = _git(
        repo_root,
        "ls-tree",
        "-z",
        "--full-tree",
        revision,
        "--",
        path_text,
    )
    entries = [entry for entry in output.split(b"\0") if entry]
    if not entries:
        return None
    if len(entries) != 1:
        raise ResolutionError(f"{description} resolved to multiple Git tree entries")
    metadata, separator, raw_path = entries[0].partition(b"\t")
    fields = metadata.split()
    if not separator or len(fields) != 3:
        raise ResolutionError(f"{description} has malformed Git tree metadata")
    mode, object_type, object_id = (
        field.decode("ascii", errors="strict") for field in fields
    )
    actual_path = raw_path.decode("utf-8", errors="surrogateescape")
    if actual_path != path_text:
        raise ResolutionError(f"{description} Git tree path did not match exactly")
    if object_type != "blob" or not mode.startswith("100"):
        raise ResolutionError(f"{description} must be a regular non-symlink Git blob")
    return object_id


def _worktree_blob(
    repo_root: Path,
    relative_path: PurePosixPath,
    expected_blob: str,
    description: str,
) -> None:
    """Require a worktree file to be regular and identical to the head blob."""
    path = repo_root.joinpath(*relative_path.parts)
    if not path.is_file() or path.is_symlink():
        raise ResolutionError(f"{description} must be a regular non-symlink file: {path}")
    current_blob = _git(repo_root, "hash-object", "--no-filters", "--", str(path))
    if current_blob.decode("ascii", errors="strict").strip() != expected_blob:
        raise ResolutionError(f"{description} does not match the validated head blob")


def _blob_object(
    repo_root: Path,
    revision: str,
    relative_path: PurePosixPath,
    description: str,
) -> dict[str, Any]:
    """Parse one validated Git blob as a JSON object."""
    content = _git(repo_root, "show", f"{revision}:{relative_path.as_posix()}")
    try:
        payload: Any = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResolutionError(f"{description} is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResolutionError(f"{description} must be a JSON object")
    return payload


def _validate_segment_pattern(segment: str, raw_pattern: str) -> None:
    """Validate one slash-free minimatch subset segment fail-closed."""
    if segment == "**":
        return
    if "**" in segment or any(character in segment for character in "{}()|"):
        raise ResolutionError(f"unsafe npm workspace pattern: {raw_pattern!r}")
    without_classes = _BRACKET_CLASS_RE.sub("", segment)
    if "[" in without_classes or "]" in without_classes:
        raise ResolutionError(f"unsafe npm workspace pattern: {raw_pattern!r}")


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
            raise ResolutionError("npm workspace patterns must be non-empty strings")
        if raw_pattern.startswith("!") or "\\" in raw_pattern:
            raise ResolutionError(f"unsafe npm workspace pattern: {raw_pattern!r}")
        if any(ord(character) < 32 or ord(character) == 127 for character in raw_pattern):
            raise ResolutionError(f"unsafe npm workspace pattern: {raw_pattern!r}")

        normalized = raw_pattern.rstrip("/")
        segments = normalized.split("/")
        if (
            raw_pattern.startswith("/")
            or not normalized
            or any(segment in {"", ".", "..", "node_modules"} for segment in segments)
        ):
            raise ResolutionError(f"unsafe npm workspace pattern: {raw_pattern!r}")
        for segment in segments:
            _validate_segment_pattern(segment, raw_pattern)
        patterns.append("/".join(segments))
    return patterns


def _is_declared_workspace(relative_package: PurePosixPath, patterns: list[str]) -> bool:
    """Return whether a path fully matches one anchored workspace pattern."""
    path_parts = relative_package.parts

    for pattern in patterns:
        pattern_parts = tuple(pattern.split("/"))

        @lru_cache(maxsize=None)
        def matches(path_index: int, pattern_index: int) -> bool:
            """Match anchored single-segment globs and recursive ``**`` tokens."""
            if pattern_index == len(pattern_parts):
                return path_index == len(path_parts)
            token = pattern_parts[pattern_index]
            if token == "**":
                return matches(path_index, pattern_index + 1) or (
                    path_index < len(path_parts)
                    and matches(path_index + 1, pattern_index)
                )
            if path_index >= len(path_parts):
                return False
            return fnmatch.fnmatchcase(path_parts[path_index], token) and matches(
                path_index + 1,
                pattern_index + 1,
            )

        if matches(0, 0):
            return True
    return False


def _lock_covers(lock_data: dict[str, Any], relative_package: str) -> bool:
    """Return whether an npm v2/v3 lock has an exact object package entry."""
    lockfile_version = lock_data.get("lockfileVersion")
    if (
        not isinstance(lockfile_version, int)
        or isinstance(lockfile_version, bool)
        or lockfile_version not in SUPPORTED_LOCKFILE_VERSIONS
    ):
        raise ResolutionError("npm lockfileVersion must be the supported integer 2 or 3")
    packages = lock_data.get("packages")
    if not isinstance(packages, dict):
        raise ResolutionError("npm lockfile must contain a packages object")
    return isinstance(packages.get(relative_package), dict)


def _validated_lock(
    repo_root: Path,
    candidate: PurePosixPath,
    head_sha: str,
) -> tuple[PurePosixPath, str] | None:
    """Return the authoritative live-head npm lock path and blob SHA."""
    for lock_name in NPM_LOCK_NAMES:
        lock_path = candidate / lock_name
        head_blob = _tree_blob(repo_root, head_sha, lock_path, "head npm lock")
        if head_blob is None:
            continue
        _worktree_blob(repo_root, lock_path, head_blob, "npm lockfile")
        return lock_path, head_blob
    return None


def _validated_manifest(
    repo_root: Path,
    candidate: PurePosixPath,
    head_sha: str,
) -> tuple[PurePosixPath, str]:
    """Return regular live-head manifest metadata for one candidate owner."""
    manifest_path = candidate / "package.json"
    head_blob = _tree_blob(repo_root, head_sha, manifest_path, "head package manifest")
    if head_blob is None:
        raise ResolutionError(
            f"npm lock owner manifest {manifest_path.as_posix()!r} is absent from validated head"
        )
    _worktree_blob(repo_root, manifest_path, head_blob, "npm lock-owner manifest")
    return manifest_path, head_blob


def resolve_install_root(
    repo_root: Path,
    package_dir: Path,
    base_sha: str,
    head_sha: str,
) -> str:
    """Return the nearest validated npm lock owner for ``package_dir``.

    ``.`` denotes the repository root. Ownership is established from the exact
    live-validated head tree and matching worktree. The caller still validates
    ``base_sha`` because the central lock receipt may authenticate either base
    or head, but dependency/workspace updates in the current head are allowed.
    """
    if repo_root.is_symlink():
        raise ResolutionError("repository root must be a real non-symlink directory")
    try:
        root = repo_root.resolve(strict=True)
    except OSError as exc:
        raise ResolutionError("repository root must be a real non-symlink directory") from exc
    if not root.is_dir() or root != Path(os.path.abspath(repo_root)):
        raise ResolutionError("repository root must be a real non-symlink directory")
    package_relative = _relative_path(root, package_dir, "npm package directory")
    package = root.joinpath(*package_relative.parts)
    if not package.is_dir() or package.is_symlink():
        raise ResolutionError("npm package directory must be a real non-symlink directory")

    _validate_revision(root, base_sha, "base SHA")
    _validate_revision(root, head_sha, "head SHA")

    selected_manifest = package_relative / "package.json"
    selected_head_blob = _tree_blob(
        root, head_sha, selected_manifest, "selected npm package manifest"
    )
    if selected_head_blob is None:
        raise ResolutionError("selected npm package manifest is absent from validated head")
    _worktree_blob(
        root,
        selected_manifest,
        selected_head_blob,
        "selected npm package manifest",
    )

    candidate = package_relative
    while True:
        validated_lock = _validated_lock(root, candidate, head_sha)
        if validated_lock is not None:
            lock_path, _lock_blob = validated_lock
            manifest_path, _manifest_blob = _validated_manifest(root, candidate, head_sha)
            lock_data = _blob_object(root, head_sha, lock_path, "head npm lockfile")
            if candidate == package_relative:
                if _lock_covers(lock_data, ""):
                    return candidate.as_posix() or "."
            else:
                relative_package = package_relative.relative_to(candidate)
                package_data = _blob_object(
                    root,
                    head_sha,
                    manifest_path,
                    "head npm workspace manifest",
                )
                patterns = _workspace_patterns(package_data)
                if _is_declared_workspace(relative_package, patterns) and _lock_covers(
                    lock_data, relative_package.as_posix()
                ):
                    return candidate.as_posix() or "."

        if candidate == PurePosixPath("."):
            break
        parent = candidate.parent
        candidate = parent if parent != PurePosixPath("") else PurePosixPath(".")

    raise ResolutionError(
        "no validated package-lock.json or npm-shrinkwrap.json owns the npm package"
    )


def _validated_cli_output(value: str) -> str:
    """Return one safe single-line repository-relative resolver result."""
    if not value or "\\" in value or any(
        ord(character) < 32 or ord(character) == 127 for character in value
    ):
        raise ResolutionError("resolved npm install root contains unsafe characters")
    candidate = PurePosixPath(value)
    normalized = candidate.as_posix()
    if candidate.is_absolute() or ".." in candidate.parts or normalized != value:
        raise ResolutionError("resolved npm install root is not a safe normalized relative path")
    return normalized


def main(argv: list[str] | None = None) -> int:
    """Resolve and print one validated repository-relative npm install root."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=Path)
    parser.add_argument("--package-dir", required=True, type=Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", required=True)
    args = parser.parse_args(argv)
    try:
        resolved_root = resolve_install_root(
            args.repo_root,
            args.package_dir,
            args.base_sha,
            args.head_sha,
        )
        print(_validated_cli_output(resolved_root))
    except (OSError, ResolutionError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
