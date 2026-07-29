#!/usr/bin/env python3
"""Materialize hash-pinned Python locks from a validated pull-request base commit."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
HASH_LOCK_NAMES = frozenset({"requirements-hashes.txt"})


def _git(repo_root: pathlib.Path, *args: str) -> bytes:
    """Run one read-only git command in the materialized repository."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {stderr}")
    return completed.stdout


def base_hash_locks(repo_root: pathlib.Path, base_sha: str) -> list[tuple[str, bytes]]:
    """Return regular hash-lock blobs from the exact validated base commit."""
    if not SHA_RE.fullmatch(base_sha):
        raise ValueError("base SHA must be exactly 40 hexadecimal characters")

    locks: list[tuple[str, bytes]] = []
    entries = _git(repo_root, "ls-tree", "-r", "-z", "--full-tree", base_sha)
    for raw_entry in entries.split(b"\0"):
        if not raw_entry:
            continue
        metadata, separator, raw_path = raw_entry.partition(b"\t")
        if not separator:
            raise RuntimeError("git ls-tree returned a malformed entry")
        fields = metadata.split()
        if len(fields) != 3:
            raise RuntimeError("git ls-tree returned malformed metadata")
        mode, object_type, _object_id = (
            field.decode("ascii", errors="strict") for field in fields
        )
        path = raw_path.decode("utf-8", errors="surrogateescape")
        candidate = pathlib.PurePosixPath(path)
        if (
            object_type != "blob"
            or not mode.startswith("100")
            or candidate.is_absolute()
            or ".." in candidate.parts
            or candidate.name not in HASH_LOCK_NAMES
        ):
            continue
        locks.append((path, _git(repo_root, "show", f"{base_sha}:{path}")))
    return sorted(locks, key=lambda item: item[0])


def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
) -> list[dict[str, str]]:
    """Write base lock blobs under generated names safe for a Docker build context."""
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    for index, (source_path, content) in enumerate(
        base_hash_locks(repo_root.resolve(), base_sha)
    ):
        generated_name = f"requirements-{index:03d}.txt"
        destination = output_dir / generated_name
        destination.write_bytes(content)
        manifest.append({"file": generated_name, "source": source_path})

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "manifest.txt").write_text(
        "".join(f"{entry['file']}\n" for entry in manifest),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Materialize base locks and report exactly which trusted paths were selected."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)

    try:
        manifest = materialize(args.repo_root, args.base_sha, args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            f"::error::Could not materialize base Python locks: {exc}", file=sys.stderr
        )
        return 1

    if manifest:
        for entry in manifest:
            print(
                "Materialized trusted base Python lock "
                f"{entry['source']} as {entry['file']}."
            )
    else:
        print(
            "No tracked requirements-hashes.txt files exist at the validated base SHA."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
