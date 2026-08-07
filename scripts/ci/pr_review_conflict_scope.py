"""Enforce the file boundary of OpenCode-assisted merge-conflict repair.

The conflict worker snapshots every tracked and non-ignored untracked worktree
path after Git has merged the protected base but before the model runs. After
OpenCode exits and temporary configuration files are restored, this module
compares the live worktree with that snapshot. Only paths that Git reported as
unmerged conflict paths may differ; any other changed, created, deleted, or
retargeted path fails closed before the workflow stages a commit.

The module never executes pull-request code. It uses a fixed, validated system
Git executable only to enumerate path names and hashes regular-file bytes
directly with SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_SCHEMA_VERSION = 1
_MAX_PATHS = 100_000
_MAX_PATH_BYTES = 4_096
_HASH_CHUNK_BYTES = 1024 * 1024
_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")


def _validated_root(root: Path) -> Path:
    """Return a canonical, non-symlink repository directory."""
    candidate = root.absolute()
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("repository root must be a non-symlink directory")
    return candidate


def _validated_relative_path(raw_path: str) -> str:
    """Return one bounded repository-relative path or raise ``ValueError``."""
    if not raw_path:
        raise ValueError("repository path must not be empty")
    if len(os.fsencode(raw_path)) > _MAX_PATH_BYTES:
        raise ValueError("repository path exceeds the byte limit")
    path = Path(raw_path)
    normalized_path = path.as_posix()
    if (
        path.is_absolute()
        or normalized_path != raw_path
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("repository path must be a normalized relative path")
    return raw_path


def _bounded_paths(paths: Sequence[str], *, source_name: str) -> tuple[str, ...]:
    """Validate, deduplicate, sort, and bound an untrusted path inventory."""
    if len(paths) > _MAX_PATHS:
        raise ValueError(f"{source_name} exceeds the path limit")
    return tuple(sorted({_validated_relative_path(path) for path in paths}))


def _trusted_git_executable() -> str:
    """Return the fixed regular executable used for security-sensitive Git reads."""
    candidate = _TRUSTED_GIT_EXECUTABLE
    if not candidate.is_absolute():
        raise RuntimeError("trusted Git executable path must be absolute")
    try:
        metadata = candidate.lstat()
    except OSError as exc:
        raise RuntimeError("trusted Git executable is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or not os.access(candidate, os.X_OK):
        raise RuntimeError("trusted Git executable must be a regular executable")
    return os.fspath(candidate)


def _git_paths(root: Path) -> tuple[str, ...]:
    """Return tracked and non-ignored untracked worktree paths from Git."""
    completed = subprocess.run(
        [
            _trusted_git_executable(),
            "-C",
            str(root),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        check=True,
        capture_output=True,
    )
    raw_paths = [os.fsdecode(item) for item in completed.stdout.split(b"\0") if item]
    return _bounded_paths(raw_paths, source_name="repository inventory")


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one regular file without loading it whole."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(root: Path, relative_path: str) -> dict[str, Any]:
    """Describe one worktree path without following symbolic links."""
    path = root / relative_path
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return {"kind": "missing"}

    mode = stat.S_IMODE(metadata.st_mode)
    if stat.S_ISREG(metadata.st_mode):
        return {
            "kind": "file",
            "mode": mode,
            "size": metadata.st_size,
            "sha256": _sha256_file(path),
        }
    if stat.S_ISLNK(metadata.st_mode):
        return {
            "kind": "symlink",
            "mode": mode,
            "target": os.readlink(path),
        }
    return {"kind": "other", "mode": mode}


def build_snapshot(root: Path) -> dict[str, Any]:
    """Build a deterministic worktree snapshot after the protected-base merge."""
    canonical_root = _validated_root(root)
    entries = {
        relative_path: _fingerprint(canonical_root, relative_path)
        for relative_path in _git_paths(canonical_root)
    }
    return {"schema_version": _SCHEMA_VERSION, "entries": entries}


def write_snapshot(root: Path, output: Path) -> None:
    """Write one deterministic UTF-8 JSON worktree snapshot."""
    document = build_snapshot(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(document, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _validated_fingerprint(value: object) -> Mapping[str, Any]:
    """Validate one serialized fingerprint object."""
    if not isinstance(value, dict):
        raise ValueError("snapshot entry must be an object")
    kind = value.get("kind")
    required_keys = {
        "missing": {"kind"},
        "file": {"kind", "mode", "size", "sha256"},
        "symlink": {"kind", "mode", "target"},
        "other": {"kind", "mode"},
    }
    if kind not in required_keys or set(value) != required_keys[kind]:
        raise ValueError("snapshot entry has an invalid fingerprint schema")
    return value


def _load_snapshot(snapshot_path: Path) -> dict[str, Mapping[str, Any]]:
    """Load and validate one supported snapshot document."""
    try:
        document = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("snapshot document could not be decoded") from exc
    if not isinstance(document, dict):
        raise ValueError("snapshot document must be an object")
    if set(document) != {"schema_version", "entries"}:
        raise ValueError("snapshot document has unexpected fields")
    if document["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("snapshot document uses an unsupported schema version")
    entries = document["entries"]
    if not isinstance(entries, dict):
        raise ValueError("snapshot entries must be an object")
    if len(entries) > _MAX_PATHS:
        raise ValueError("snapshot entries exceed the path limit")

    validated: dict[str, Mapping[str, Any]] = {}
    for raw_path, fingerprint in entries.items():
        relative_path = _validated_relative_path(raw_path)
        validated[relative_path] = _validated_fingerprint(fingerprint)
    return validated


def _read_allowed_paths(path: Path) -> tuple[str, ...]:
    """Read the NUL-delimited authoritative Git conflict-path allowlist."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("allowed-path inventory could not be read") from exc
    raw_paths = [os.fsdecode(item) for item in payload.split(b"\0") if item]
    return _bounded_paths(raw_paths, source_name="allowed-path inventory")


def verify_snapshot(
    root: Path, snapshot_path: Path, allowed_paths_path: Path
) -> tuple[str, ...]:
    """Return paths changed by the model outside Git's conflict allowlist."""
    canonical_root = _validated_root(root)
    before = _load_snapshot(snapshot_path)
    allowed_paths = frozenset(_read_allowed_paths(allowed_paths_path))
    unknown_allowed = allowed_paths.difference(before)
    if unknown_allowed:
        raise ValueError("allowed path is absent from the pre-model snapshot")

    current_paths = _git_paths(canonical_root)
    all_paths = tuple(sorted(set(before).union(current_paths)))
    violations = tuple(
        relative_path
        for relative_path in all_paths
        if relative_path not in allowed_paths
        and before.get(relative_path, {"kind": "missing"})
        != _fingerprint(canonical_root, relative_path)
    )
    return violations


def _parser() -> argparse.ArgumentParser:
    """Build the command-line parser for snapshot and verification phases."""
    parser = argparse.ArgumentParser(prog="pr-review-conflict-scope")
    subcommands = parser.add_subparsers(dest="command", required=True)

    snapshot = subcommands.add_parser("snapshot")
    snapshot.add_argument("--root", type=Path, required=True)
    snapshot.add_argument("--output", type=Path, required=True)

    verify = subcommands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    verify.add_argument("--snapshot", type=Path, required=True)
    verify.add_argument("--allowed-paths", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one conflict-scope phase and return a process exit code."""
    arguments = _parser().parse_args(argv)
    if arguments.command == "snapshot":
        write_snapshot(arguments.root, arguments.output)
        print("Conflict-resolution worktree snapshot recorded.")
        return 0

    violations = verify_snapshot(
        arguments.root, arguments.snapshot, arguments.allowed_paths
    )
    if violations:
        encoded = json.dumps(violations, ensure_ascii=True)
        print(
            f"Conflict-resolution model changed paths outside its allowlist: {encoded}",
            file=sys.stderr,
        )
        return 1
    print("Conflict-resolution model write scope verified.")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through ``main`` tests.
    raise SystemExit(main())