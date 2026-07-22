#!/usr/bin/env python3
"""Materialize strictly hashed Python locks from one trusted base commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath

SHA_RE = re.compile(r"[0-9a-fA-F]{40}")
SAFE_PATH_RE = re.compile(r"(?:[A-Za-z0-9._-]+/)*requirements-hashes\.txt")
PINNED_REQUIREMENT_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9_,.-]+\])?"
    r"==[A-Za-z0-9][A-Za-z0-9.!+_-]*(?:\s*;\s*.+)?"
)
HASH_RE = re.compile(r"--hash=sha256:[0-9a-f]{64}")
MAX_LOCKS = 8
MAX_LOCK_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES = 20 * 1024 * 1024
MAX_TREE_OUTPUT_BYTES = 32 * 1024 * 1024
GIT_EXECUTABLE = shutil.which("git")


def validated_git_executable() -> str:
    """Return the absolute, executable Git binary selected from the trusted runner PATH."""
    candidate = GIT_EXECUTABLE
    if not candidate or not Path(candidate).is_absolute():
        raise RuntimeError("an absolute Git executable path is required")
    try:
        resolved = Path(candidate).resolve(strict=True)
    except OSError as exc:
        raise RuntimeError("the configured Git executable is unavailable") from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise RuntimeError("the configured Git executable failed validation")
    return str(resolved)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if not SHA_RE.fullmatch(args.base_sha):
        parser.error("--base-sha must be a 40-character hexadecimal commit SHA")
    return args


def git_bytes(repo_root: Path, *args: str) -> bytes:
    """Run a bounded read-only Git command without shell interpretation."""
    completed = subprocess.run(  # nosec B603
        [validated_git_executable(), "-C", str(repo_root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    if len(completed.stdout) > MAX_TREE_OUTPUT_BYTES:
        raise ValueError("Git output exceeded the bounded materialization limit")
    return completed.stdout


def validate_repo_root(repo_root: Path, base_sha: str) -> Path:
    """Resolve a repository containing the exact requested base commit."""
    resolved = repo_root.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("--repo-root must resolve to a directory")
    commit = git_bytes(resolved, "rev-parse", f"{base_sha}^{{commit}}").decode().strip()
    if commit.lower() != base_sha.lower():
        raise ValueError("--base-sha did not resolve to the exact requested commit")
    return resolved


def safe_output_dir(output_dir: Path) -> Path:
    """Return a fresh output path without symbolic-link ancestors."""
    absolute = output_dir.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError("--output-dir contains a symbolic-link component")
    if absolute.exists() or absolute.is_symlink():
        raise ValueError("--output-dir must not already exist")
    return absolute


def logical_requirement_lines(text: str) -> list[str]:
    """Return non-comment requirement records with continuations joined."""
    logical: list[str] = []
    pending = ""
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        continuation = stripped.endswith("\\")
        fragment = stripped[:-1].rstrip() if continuation else stripped
        pending = f"{pending} {fragment}".strip()
        if not continuation:
            logical.append(pending)
            pending = ""
    if pending:
        raise ValueError("hashed requirements ended with an incomplete continuation")
    return logical


def validate_lock_content(data: bytes) -> str:
    """Accept only pinned package records with one or more SHA-256 hashes."""
    if len(data) > MAX_LOCK_BYTES:
        raise ValueError("hashed requirements file exceeds the per-lock size limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("hashed requirements file must be UTF-8") from exc
    if "\x00" in text:
        raise ValueError("hashed requirements file contains a NUL byte")
    records = logical_requirement_lines(text)
    if not records:
        raise ValueError("hashed requirements file contains no package records")
    for record in records:
        hashes = HASH_RE.findall(record)
        requirement = HASH_RE.sub("", record).strip()
        if not hashes or not PINNED_REQUIREMENT_RE.fullmatch(requirement):
            raise ValueError(
                "hashed requirements must contain only pinned package records "
                "and sha256 hashes"
            )
    return text


def parse_lock_entries(tree: bytes) -> list[tuple[str, str, int]]:
    """Select bounded regular hashed-lock blobs from NUL-delimited ls-tree output."""
    selected: list[tuple[str, str, int]] = []
    total_bytes = 0
    for record in tree.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, oid, size_text = metadata.decode("ascii").split()
            path = raw_path.decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            raise ValueError("could not parse Git tree entry") from exc
        pure_path = PurePosixPath(path)
        if pure_path.name != "requirements-hashes.txt":
            continue
        if (
            pure_path.is_absolute()
            or ".." in pure_path.parts
            or pure_path.as_posix() != path
        ):
            raise ValueError(f"hashed requirements path or size is unsafe: {path}")
        if mode != "100644" or kind != "blob" or not SHA_RE.fullmatch(oid):
            raise ValueError(f"hashed requirements must be a regular file: {path}")
        if not size_text.isdigit() or not SAFE_PATH_RE.fullmatch(path):
            raise ValueError(f"hashed requirements path or size is unsafe: {path}")
        size = int(size_text)
        if size > MAX_LOCK_BYTES:
            raise ValueError(f"hashed requirements file is too large: {path}")
        total_bytes += size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError("hashed requirements exceed the aggregate size limit")
        selected.append((path, oid, size))
        if len(selected) > MAX_LOCKS:
            raise ValueError("too many hashed requirements files in the base commit")
    return selected


def write_exclusive(path: Path, data: bytes) -> None:
    """Write a non-executable file without following a final symlink."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        handle = os.fdopen(descriptor, "wb")
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        raise
    with handle:
        handle.write(data)
    path.chmod(0o444)


def materialize(repo_root: Path, base_sha: str, output_dir: Path) -> dict[str, object]:
    """Materialize validated base locks and a project-to-environment manifest."""
    repo = validate_repo_root(repo_root, base_sha)
    output = safe_output_dir(output_dir)
    tree = git_bytes(repo, "ls-tree", "-r", "-z", "-l", "--full-tree", base_sha)
    entries = parse_lock_entries(tree)
    output.mkdir(mode=0o755)
    locks: list[dict[str, object]] = []
    manifest_lines: list[str] = []
    for index, (path, oid, expected_size) in enumerate(entries):
        data = git_bytes(repo, "cat-file", "blob", oid)
        if len(data) != expected_size:
            raise RuntimeError(f"Git blob size changed after tree validation: {path}")
        validate_lock_content(data)
        slug = f"lock-{index:03d}"
        filename = f"{slug}.txt"
        project_dir = PurePosixPath(path).parent.as_posix()
        if project_dir == ".":
            project_dir = "."
        write_exclusive(output / filename, data)
        manifest_lines.append(f"{project_dir}\t{slug}\t{filename}\n")
        locks.append(
            {
                "project_dir": project_dir,
                "path": path,
                "oid": oid,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "environment": slug,
                "file": filename,
            }
        )
    write_exclusive(output / "manifest.tsv", "".join(manifest_lines).encode())
    metadata: dict[str, object] = {
        "schema": 1,
        "base_sha": base_sha.lower(),
        "locks": locks,
    }
    write_exclusive(
        output / "manifest.json",
        (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode(),
    )
    return metadata


def main(argv: list[str] | None = None) -> int:
    """Run base-lock materialization."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        metadata = materialize(args.repo_root, args.base_sha, args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"base Python lock materialization failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(metadata, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main()
    raise SystemExit(main())
