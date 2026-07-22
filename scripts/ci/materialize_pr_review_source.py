#!/usr/bin/env python3
"""Materialize an inert PR source tree from an isolated bare Git repository.

The privileged OpenCode review job must inspect pull-request content without
checking an untrusted commit out into the trusted workflow repository.  This
helper copies only validated Git blobs into a fresh directory, strips every
executable bit, represents symbolic links as inert regular files, and connects
read-only Git queries to the separate bare object store through a trusted
``.git`` pointer.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import shutil
import stat

# Git is invoked through an absolute executable path, a fixed argv, and no shell.
import subprocess  # nosec B404
import sys
import time
from typing import BinaryIO


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
REGULAR_MODES = {"100644", "100755"}
SYMLINK_MODE = "120000"
GITLINK_MODE = "160000"
RESERVED_ROOTS = {".codegraph", ".git"}
DEFAULT_MAX_FILES = 100_000
DEFAULT_MAX_BYTES = 1_073_741_824
DEFAULT_MAX_TREE_METADATA_BYTES = 67_108_864
DEFAULT_TREE_TIMEOUT_SECONDS = 60
TREE_READ_CHUNK_BYTES = 65_536
MAX_TREE_RECORD_BYTES = 1_048_576
TREE_ENTRY_METADATA_OVERHEAD_BYTES = 128
GIT_EXECUTABLE = shutil.which("git", path=os.defpath)
TRUSTED_GIT_OWNER_UID = 0
if not GIT_EXECUTABLE or not Path(GIT_EXECUTABLE).is_absolute():
    raise RuntimeError("an absolute Git executable path is required")


def validated_git_executable() -> str:
    """Return a trusted absolute Git binary for privileged materialization."""
    candidate = Path(GIT_EXECUTABLE or "")
    if not GIT_EXECUTABLE or not candidate.is_absolute():
        raise RuntimeError("an absolute Git executable path is required")
    try:
        resolved = candidate.resolve(strict=True)
        candidate_parent = candidate.parent.resolve(strict=True)
        resolved_parent = resolved.parent.resolve(strict=True)
        resolved_stat = resolved.stat()
        parent_stats = (candidate_parent.stat(), resolved_parent.stat())
    except OSError as exc:
        raise RuntimeError("the configured Git executable is unavailable") from exc
    if (
        not resolved.is_file()
        or not os.access(resolved, os.X_OK)
        or resolved_stat.st_uid != TRUSTED_GIT_OWNER_UID
        or resolved_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or any(
            parent_stat.st_uid != TRUSTED_GIT_OWNER_UID
            or parent_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            for parent_stat in parent_stats
        )
    ):
        raise RuntimeError("the configured Git executable failed trust validation")
    return str(resolved)


def positive_int(value: str) -> int:
    """Parse a positive integer command-line limit."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("value must be positive")
    return parsed


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Precondition: the immediate parent of --output-dir must already exist.",
    )
    parser.add_argument("--git-dir", type=Path, required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="fresh output path whose immediate parent already exists",
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--max-files", type=positive_int, default=DEFAULT_MAX_FILES)
    parser.add_argument("--max-bytes", type=positive_int, default=DEFAULT_MAX_BYTES)
    parser.add_argument(
        "--max-tree-metadata-bytes",
        type=positive_int,
        default=DEFAULT_MAX_TREE_METADATA_BYTES,
    )
    parser.add_argument(
        "--tree-timeout-seconds",
        type=positive_int,
        default=DEFAULT_TREE_TIMEOUT_SECONDS,
    )
    args = parser.parse_args(argv)
    if not SHA_RE.fullmatch(args.head_sha):
        parser.error("--head-sha must be a 40-character hexadecimal commit SHA")
    return args


def git_bytes(git_dir: Path, *args: str) -> bytes:
    """Run a read-only Git command against the isolated object store."""
    # argv only; the Git directory and commit inputs are validated before use.
    completed = subprocess.run(  # nosec B603
        [validated_git_executable(), f"--git-dir={git_dir}", *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(detail or f"git {' '.join(args)} failed")
    return completed.stdout


def validate_git_dir(git_dir: Path, head_sha: str) -> Path:
    """Return a resolved, bare Git directory containing the requested commit."""
    resolved = git_dir.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("--git-dir must resolve to a directory")
    bare = git_bytes(resolved, "rev-parse", "--is-bare-repository").decode().strip()
    if bare != "true":
        raise ValueError("--git-dir must be an isolated bare repository")
    commit = git_bytes(resolved, "rev-parse", f"{head_sha}^{{commit}}").decode().strip()
    if commit.lower() != head_sha.lower():
        raise ValueError("--head-sha did not resolve to the exact requested commit")
    return resolved


def reject_symlink_components(path: Path, option: str) -> Path:
    """Return an absolute path only when no existing component is a symlink."""
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise ValueError(f"{option} contains a symbolic-link path component")
    return absolute


def validate_output_path(output_dir: Path, git_dir: Path) -> Path:
    """Require a fresh output path that cannot overlap the Git object store."""
    output = reject_symlink_components(output_dir, "--output-dir")
    if output.exists() or output.is_symlink():
        raise ValueError("--output-dir must not already exist")
    output_parent = output.parent.resolve(strict=True)
    output = output_parent / output.name
    if output == git_dir or output in git_dir.parents or git_dir in output.parents:
        raise ValueError("--output-dir and --git-dir must not overlap")
    return output


def safe_relative_path(raw_path: bytes) -> PurePosixPath:
    """Decode and validate a Git tree path without accepting traversal."""
    try:
        decoded = raw_path.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Git tree contains a non-UTF-8 path") from exc
    path = PurePosixPath(decoded)
    if not decoded or decoded.startswith("/") or path.is_absolute():
        raise ValueError(f"unsafe absolute or empty Git tree path: {decoded!r}")
    if (
        "\\" in decoded
        or decoded != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError(f"unsafe Git tree path component: {decoded!r}")
    return path


def parse_tree_entry(
    record: bytes,
) -> tuple[str, str, str, int, PurePosixPath]:
    """Parse one bounded NUL-delimited ``git ls-tree`` record."""
    try:
        metadata, raw_path = record.split(b"\t", 1)
        mode_raw, kind_raw, oid_raw, size_raw = metadata.split(maxsplit=3)
        mode = mode_raw.decode("ascii")
        kind = kind_raw.decode("ascii")
        oid = oid_raw.decode("ascii")
        size_text = size_raw.decode("ascii")
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("could not parse Git tree entry") from exc
    if not SHA_RE.fullmatch(oid):
        raise ValueError("Git tree entry has an invalid object id")
    if mode == GITLINK_MODE and kind == "commit" and size_text == "-":
        size = len(f"Submodule commit {oid}\n".encode())
    elif kind == "blob" and size_text.isdigit():
        size = int(size_text)
    else:
        raise ValueError(f"unsupported Git tree entry type/mode: {kind}/{mode}")
    return mode, kind, oid, size, safe_relative_path(raw_path)


def open_tree_reader(git_dir: Path, head_sha: str) -> subprocess.Popen[bytes]:
    """Start bounded streaming enumeration of one exact commit tree."""
    return subprocess.Popen(  # nosec B603
        [
            GIT_EXECUTABLE,
            f"--git-dir={git_dir}",
            "ls-tree",
            "-r",
            "-z",
            "-l",
            "--full-tree",
            head_sha,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
    )


def terminate_process(process: subprocess.Popen[bytes]) -> None:
    """Stop a tree producer promptly after a limit or parser failure."""
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def parse_tree(
    git_dir: Path,
    head_sha: str,
    *,
    max_files: int,
    max_bytes: int,
    timeout_seconds: int,
    max_tree_metadata_bytes: int = DEFAULT_MAX_TREE_METADATA_BYTES,
) -> tuple[list[tuple[str, str, str, int, PurePosixPath]], int]:
    """Stream and bound validated recursive Git tree entries."""
    process = open_tree_reader(git_dir, head_sha)
    stdout = process.stdout
    if stdout is None:
        terminate_process(process)
        raise RuntimeError("Git ls-tree stdout pipe is unavailable")

    selector = selectors.DefaultSelector()
    selector.register(stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_seconds
    pending = bytearray()
    entries: list[tuple[str, str, str, int, PurePosixPath]] = []
    total_bytes = 0
    total_metadata_bytes = 0
    try:
        reached_eof = False
        while not reached_eof:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError(
                    f"Git tree enumeration exceeded --tree-timeout-seconds ({timeout_seconds})"
                )
            events = selector.select(timeout=min(1.0, remaining))
            if not events:
                if process.poll() is not None:
                    reached_eof = True
                continue
            chunk = os.read(stdout.fileno(), TREE_READ_CHUNK_BYTES)
            if not chunk:
                reached_eof = True
                continue
            pending.extend(chunk)
            while True:
                separator = pending.find(0)
                if separator < 0:
                    if len(pending) > MAX_TREE_RECORD_BYTES:
                        raise ValueError(
                            "Git tree entry exceeds the bounded record-size limit"
                        )
                    break
                if separator > MAX_TREE_RECORD_BYTES:
                    raise ValueError(
                        "Git tree entry exceeds the bounded record-size limit"
                    )
                record = bytes(pending[:separator])
                del pending[: separator + 1]
                if not record:
                    continue
                next_metadata_bytes = (
                    total_metadata_bytes
                    + len(record)
                    + TREE_ENTRY_METADATA_OVERHEAD_BYTES
                )
                if next_metadata_bytes > max_tree_metadata_bytes:
                    raise ValueError(
                        "Git tree exceeds --max-tree-metadata-bytes "
                        f"({next_metadata_bytes} > {max_tree_metadata_bytes})"
                    )
                entry = parse_tree_entry(record)
                next_file_count = len(entries) + 1
                if next_file_count > max_files:
                    raise ValueError(
                        f"Git tree exceeds --max-files ({next_file_count} > {max_files})"
                    )
                next_total_bytes = total_bytes + entry[3]
                if next_total_bytes > max_bytes:
                    raise ValueError(
                        f"Git tree exceeds --max-bytes ({next_total_bytes} > {max_bytes})"
                    )
                entries.append(entry)
                total_bytes = next_total_bytes
                total_metadata_bytes = next_metadata_bytes
        if pending:
            raise ValueError("Git tree output ended with an unterminated record")
    except BaseException:
        terminate_process(process)
        raise
    finally:
        selector.close()

    try:
        return_code = process.wait(timeout=5)
    except subprocess.TimeoutExpired as exc:
        terminate_process(process)
        raise RuntimeError("Git ls-tree did not exit after output completed") from exc
    stderr = (
        process.stderr.read().decode("utf-8", errors="replace").strip()
        if process.stderr
        else ""
    )
    if return_code != 0:
        raise RuntimeError(stderr or "Git ls-tree failed")
    return entries, total_bytes


def open_batch_reader(git_dir: Path) -> subprocess.Popen[bytes]:
    """Start one Git batch process for bounded blob reads."""
    # Fixed Git subcommand and no shell evaluation.
    return subprocess.Popen(  # nosec B603
        [GIT_EXECUTABLE, f"--git-dir={git_dir}", "cat-file", "--batch"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def read_blob(process: subprocess.Popen[bytes], oid: str, expected_size: int) -> bytes:
    """Read one exact blob through the long-lived Git batch process."""
    stdin: BinaryIO | None = process.stdin
    stdout: BinaryIO | None = process.stdout
    if stdin is None or stdout is None:
        raise RuntimeError("Git cat-file batch pipes are unavailable")
    stdin.write(f"{oid}\n".encode("ascii"))
    stdin.flush()
    header = stdout.readline().rstrip(b"\n")
    fields = header.split()
    if len(fields) != 3 or fields[0].decode("ascii", errors="replace") != oid:
        raise RuntimeError("Git cat-file returned an unexpected object header")
    if fields[1] != b"blob" or not fields[2].isdigit():
        raise RuntimeError("Git cat-file object is not a blob")
    actual_size = int(fields[2])
    if actual_size != expected_size:
        raise RuntimeError("Git blob size changed after tree validation")
    data = stdout.read(actual_size)
    delimiter = stdout.read(1)
    if len(data) != actual_size or delimiter != b"\n":
        raise RuntimeError("Git cat-file returned a truncated blob")
    return data


def write_inert_file(path: Path, data: bytes) -> None:
    """Create one non-executable regular file without following links."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
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


def materialize(args: argparse.Namespace) -> dict[str, object]:
    """Materialize validated inert files and return provenance metadata."""
    git_dir = validate_git_dir(args.git_dir, args.head_sha)
    output_dir = validate_output_path(args.output_dir, git_dir)
    manifest_path = reject_symlink_components(args.manifest, "--manifest")
    if manifest_path.exists() or manifest_path.is_symlink():
        raise ValueError("--manifest must not already exist")
    if manifest_path == output_dir or output_dir in manifest_path.parents:
        raise ValueError("--manifest must be outside --output-dir")

    entries, total_bytes = parse_tree(
        git_dir,
        args.head_sha,
        max_files=args.max_files,
        max_bytes=args.max_bytes,
        timeout_seconds=args.tree_timeout_seconds,
        max_tree_metadata_bytes=args.max_tree_metadata_bytes,
    )

    output_dir.mkdir(mode=0o755)
    skipped: list[dict[str, str]] = []
    special: list[dict[str, str]] = []
    written = 0
    process = open_batch_reader(git_dir)
    try:
        for mode, kind, oid, size, relative in entries:
            rendered = relative.as_posix()
            if relative.parts[0] in RESERVED_ROOTS:
                skipped.append({"path": rendered, "reason": "reserved-review-metadata"})
                continue
            destination = output_dir.joinpath(*relative.parts)
            if mode == GITLINK_MODE and kind == "commit":
                data = f"Submodule commit {oid}\n".encode()
                special.append(
                    {
                        "path": rendered,
                        "original_mode": mode,
                        "representation": "gitlink-marker",
                    }
                )
            elif kind == "blob" and mode in REGULAR_MODES | {SYMLINK_MODE}:
                data = read_blob(process, oid, size)
                if mode == SYMLINK_MODE:
                    special.append(
                        {
                            "path": rendered,
                            "original_mode": mode,
                            "representation": "inert-regular-file",
                        }
                    )
                elif mode == "100755":
                    special.append(
                        {
                            "path": rendered,
                            "original_mode": mode,
                            "representation": "non-executable-regular-file",
                        }
                    )
            else:
                raise ValueError(f"unsupported Git entry {kind}/{mode} at {rendered}")
            write_inert_file(destination, data)
            written += 1
    finally:
        if process.stdin is not None:
            process.stdin.close()
        stderr = (
            process.stderr.read().decode("utf-8", errors="replace")
            if process.stderr
            else ""
        )
        return_code = process.wait()
        if return_code != 0 and sys.exc_info()[0] is None:
            raise RuntimeError(stderr.strip() or "Git cat-file batch failed")

    git_pointer = output_dir / ".git"
    write_inert_file(git_pointer, f"gitdir: {git_dir}\n".encode())
    metadata: dict[str, object] = {
        "schema": 1,
        "head_sha": args.head_sha.lower(),
        "git_dir": str(git_dir),
        "source_dir": str(output_dir),
        "tree_entries": len(entries),
        "written_files": written,
        "tree_bytes": total_bytes,
        "skipped": skipped,
        "special_representations": special,
    }
    # Recheck after materialization so an ancestor swapped to a link cannot
    # redirect the final provenance write.
    reject_symlink_components(manifest_path, "--manifest")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_inert_file(
        manifest_path, (json.dumps(metadata, sort_keys=True, indent=2) + "\n").encode()
    )
    return metadata


def main(argv: list[str] | None = None) -> int:
    """Run the inert PR source materializer."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        metadata = materialize(args)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"materialize_pr_review_source: {exc}", file=sys.stderr)
        return 1
    print(
        "Materialized inert PR source blobs: "
        f"head={metadata['head_sha']} files={metadata['written_files']} bytes={metadata['tree_bytes']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
