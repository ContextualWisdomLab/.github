"""Enforce the file boundary of OpenCode-assisted merge-conflict repair.

The conflict worker snapshots every tracked and untracked worktree path,
including ignored paths, after Git has merged the protected base but before the
model runs. After OpenCode exits and temporary configuration files are restored,
this module compares the live worktree with that snapshot. Only paths that Git
reported as unmerged conflict paths may differ; any other changed, created,
deleted, or retargeted path fails closed before the workflow stages a commit.

The module never executes pull-request code. It uses a fixed, validated system
Git executable only to enumerate path names and hashes regular-file bytes
directly with SHA-256. Every symbolic link must resolve to a regular file that
is itself present in Git's tracked-or-non-ignored inventory, preventing links
from exposing external, ignored, dangling, or directory-backed write paths.
Security control files used to authorize or verify model writes must resolve
outside the repository worktree so the model cannot modify its own evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
_SHA256_SEAL_RE = re.compile(r"[0-9a-f]{64}\n")


def _validated_root(root: Path) -> Path:
    """Return a canonical, non-symlink repository directory.

    The last component and its immediate parent are both checked with
    ``Path.is_symlink()`` before ``resolve``. A parent swapped to a
    symbolic link after the caller constructed the path cannot redirect
    the canonical root (CWE-367).
    """
    candidate = root.absolute()
    if (
        candidate.is_symlink()
        or candidate.parent.is_symlink()
        or not candidate.is_dir()
    ):
        raise ValueError("repository root must be a non-symlink directory")
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise ValueError("repository root could not be canonicalized") from exc


def _is_within_root(root: Path, candidate: Path) -> bool:
    """Return whether ``candidate`` is the repository root or one of its descendants."""
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _validated_external_control_path(
    root: Path, path: Path, *, source_name: str
) -> Path:
    """Return a canonical control path that cannot be model-writable repository state.

    Both the caller-visible absolute path and its resolved target are checked.
    The first check rejects a control file placed directly in the worktree; the
    second rejects an outside-looking symbolic link whose target resolves back
    into the worktree. ``strict=False`` intentionally permits a new snapshot
    output whose parent does not yet exist while still resolving existing
    symbolic-link components.
    """
    candidate = path.absolute()
    resolved = candidate.resolve(strict=False)
    if _is_within_root(root, candidate) or _is_within_root(root, resolved):
        raise ValueError(f"{source_name} must remain outside the repository worktree")
    return resolved


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
    if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise RuntimeError(
            "trusted Git executable must not be group- or world-writable"
        )
    return os.fspath(candidate)


def _git_ls_files(root: Path, *arguments: str) -> tuple[str, ...]:
    """Return one NUL-delimited Git path listing decoded without loss."""
    completed = subprocess.run(
        [
            _trusted_git_executable(),
            "-C",
            str(root),
            "ls-files",
            "-z",
            *arguments,
        ],
        check=True,
        capture_output=True,
    )
    return tuple(
        os.fsdecode(item) for item in completed.stdout.split(b"\0") if item
    )


def _git_visible_paths(root: Path) -> tuple[str, ...]:
    """Return tracked and non-ignored untracked paths from Git."""
    return _bounded_paths(
        _git_ls_files(root, "--cached", "--others", "--exclude-standard"),
        source_name="reviewable repository inventory",
    )


def _git_paths(root: Path) -> tuple[str, ...]:
    """Return every tracked or untracked worktree path, including ignored paths."""
    visible_paths = _git_visible_paths(root)
    ignored_paths = _git_ls_files(
        root,
        "--others",
        "--ignored",
        "--exclude-standard",
    )
    return _bounded_paths(
        (*visible_paths, *ignored_paths),
        source_name="repository inventory",
    )


def _validate_symlink_targets(root: Path, relative_paths: Sequence[str]) -> None:
    """Require every symlink to resolve to a reviewable regular worktree file."""
    symlinks: list[tuple[str, Path]] = []
    for relative_path in relative_paths:
        link_path = root / relative_path
        try:
            link_metadata = os.lstat(link_path)
        except FileNotFoundError:
            continue
        except OSError:
            raise ValueError(
                f"repository path {relative_path!r} could not be inspected safely"
            ) from None
        if stat.S_ISLNK(link_metadata.st_mode):
            symlinks.append((relative_path, link_path))

    if not symlinks:
        return

    inventory = frozenset(_git_visible_paths(root))
    for relative_path, link_path in symlinks:
        try:
            resolved_target = link_path.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ValueError(
                f"repository symlink {relative_path!r} must resolve to a regular file"
            ) from exc
        try:
            target_relative = resolved_target.relative_to(root).as_posix()
        except ValueError as exc:
            raise ValueError(
                f"repository symlink {relative_path!r} must resolve inside the repository"
            ) from exc

        try:
            target_metadata = resolved_target.lstat()
        except OSError as exc:
            raise ValueError(
                f"repository symlink {relative_path!r} must resolve to a regular file"
            ) from exc
        if not stat.S_ISREG(target_metadata.st_mode):
            raise ValueError(
                f"repository symlink {relative_path!r} must resolve to a regular file"
            )

        normalized_target = _validated_relative_path(target_relative)
        if normalized_target not in inventory:
            raise ValueError(
                f"repository symlink {relative_path!r} target must be present in the Git inventory"
            )


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
    relative_paths = _git_paths(canonical_root)
    _validate_symlink_targets(canonical_root, relative_paths)
    entries = {
        relative_path: _fingerprint(canonical_root, relative_path)
        for relative_path in relative_paths
    }
    return {"schema_version": _SCHEMA_VERSION, "entries": entries}


def write_snapshot(root: Path, output: Path) -> None:
    """Write one deterministic snapshot to trusted storage outside the worktree."""
    canonical_root = _validated_root(root)
    trusted_output = _validated_external_control_path(
        canonical_root,
        output,
        source_name="snapshot output",
    )
    document = build_snapshot(canonical_root)
    trusted_output.parent.mkdir(parents=True, exist_ok=True)
    trusted_output.write_text(
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


def _verify_optional_allowed_path_seal(path: Path, payload: bytes) -> None:
    """Require a matching trusted SHA-256 seal when its sidecar is present."""
    seal_path = Path(f"{path}.sha256")
    try:
        seal = seal_path.read_text(encoding="ascii")
    except FileNotFoundError:
        return
    except (OSError, UnicodeError) as exc:
        raise ValueError("allowed-path seal could not be read") from exc
    if _SHA256_SEAL_RE.fullmatch(seal) is None:
        raise ValueError("allowed-path seal is malformed")
    if seal[:-1] != hashlib.sha256(payload).hexdigest():
        raise ValueError("allowed-path inventory does not match its trusted seal")


def _read_allowed_paths(path: Path) -> tuple[str, ...]:
    """Read the NUL-delimited authoritative Git conflict-path allowlist."""
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise ValueError("allowed-path inventory could not be read") from exc
    _verify_optional_allowed_path_seal(path, payload)
    raw_paths = [os.fsdecode(item) for item in payload.split(b"\0") if item]
    return _bounded_paths(raw_paths, source_name="allowed-path inventory")


def verify_snapshot(
    root: Path, snapshot_path: Path, allowed_paths_path: Path
) -> tuple[str, ...]:
    """Return model changes outside a trusted external conflict-path allowlist."""
    canonical_root = _validated_root(root)
    trusted_snapshot = _validated_external_control_path(
        canonical_root,
        snapshot_path,
        source_name="snapshot input",
    )
    trusted_allowed_paths = _validated_external_control_path(
        canonical_root,
        allowed_paths_path,
        source_name="allowed-path input",
    )
    before = _load_snapshot(trusted_snapshot)
    allowed_paths = frozenset(_read_allowed_paths(trusted_allowed_paths))
    unknown_allowed = allowed_paths.difference(before)
    if unknown_allowed:
        raise ValueError("allowed path is absent from the pre-model snapshot")

    current_paths = _git_paths(canonical_root)
    current = {
        relative_path: _fingerprint(canonical_root, relative_path)
        for relative_path in current_paths
    }
    all_paths = tuple(sorted(set(before).union(current)))
    violations = tuple(
        relative_path
        for relative_path in all_paths
        if relative_path not in allowed_paths
        and before.get(relative_path, {"kind": "missing"})
        != current.get(relative_path, {"kind": "missing"})
    )
    if violations:
        return violations

    _validate_symlink_targets(canonical_root, current_paths)
    return ()


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
