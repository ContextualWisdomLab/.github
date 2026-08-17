#!/usr/bin/env python3
"""Copy bounded Rust workspace inputs into the trusted coverage image context.

The isolated coverage sandbox is networkless and previously used Debian rustc
1.85 without ``llvm-tools-preview``. OriginWeave-style workspaces declare
``rust-version = "1.97"`` and ``edition = "2024"``, so the image must install
the repository toolchain plus llvm-tools and prefetch ``Cargo.lock`` crates
before the sandbox starts.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import struct
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by Python 3.10 CI.
    import tomli as tomllib

DEBIAN_RUSTC = (1, 85, 0)
CHANNEL_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
RUST_INPUT_NAMES = ("rust-toolchain.toml", "rust-toolchain", "Cargo.toml", "Cargo.lock")


def _resolve_git_dir(repo_root: Path) -> Path:
    """Return the git directory for a regular checkout or gitdir pointer file."""
    git_path = repo_root / ".git"
    if git_path.is_symlink():
        raise RuntimeError("git ls-files failed: .git is a symbolic link")
    if git_path.is_file():
        match = re.search(
            r"(?m)^gitdir:\s*(.+?)\s*$",
            git_path.read_text(encoding="utf-8"),
        )
        if match is None:
            raise RuntimeError("git ls-files failed: invalid gitdir pointer")
        raw = match.group(1)
        candidate = Path(raw) if Path(raw).is_absolute() else git_path.parent / raw
        if candidate.is_symlink() or not candidate.is_dir():
            raise RuntimeError("git ls-files failed: gitdir is not a regular directory")
        return candidate
    if git_path.is_dir():
        return git_path
    raise RuntimeError("git ls-files failed: not a git repository")


def _read_git_index_paths(repo_root: Path) -> bytes:
    """Return ``git ls-files -z`` bytes by parsing the on-disk git index."""
    index_path = _resolve_git_dir(repo_root) / "index"
    if index_path.is_symlink() or not index_path.is_file():
        raise RuntimeError("git ls-files failed: git index is not a regular file")
    data = index_path.read_bytes()
    if len(data) < 12 or data[:4] != b"DIRC":
        raise RuntimeError("git ls-files failed: git index header is invalid")
    version, count = struct.unpack(">II", data[4:12])
    if version not in {2, 3}:
        raise RuntimeError(f"git ls-files failed: unsupported git index version {version}")
    offset = 12
    names: list[bytes] = []
    for _ in range(count):
        if offset + 62 > len(data):
            raise RuntimeError("git ls-files failed: truncated git index")
        flags = struct.unpack(">H", data[offset + 60 : offset + 62])[0]
        header_len = 64 if flags & 0x4000 else 62
        if offset + header_len > len(data):
            raise RuntimeError("git ls-files failed: truncated git index")
        name_len = flags & 0x0FFF
        name_start = offset + header_len
        if name_len == 0x0FFF:
            nul = data.find(b"\0", name_start)
            if nul < 0:
                raise RuntimeError("git ls-files failed: truncated git index path")
            name = data[name_start:nul]
            consumed = nul + 1 - offset
        else:
            name_end = name_start + name_len
            if name_end > len(data):
                raise RuntimeError("git ls-files failed: truncated git index path")
            name = data[name_start:name_end]
            consumed = name_end + 1 - offset
        padding = (8 - (consumed % 8)) % 8
        offset += consumed + padding
        names.append(name)
    return b"\0".join(names) + (b"\0" if names else b"")


def _git(repo_root: Path, *args: str) -> bytes:
    """Return one read-only git listing from the materialized merge tree.

    Only ``ls-files -z`` is supported. The coverage image must not spawn a
    shell or ``git`` child; tracked paths come from the on-disk index.
    """
    if args != ("ls-files", "-z"):
        raise RuntimeError(f"git {args[0] if args else 'command'} failed: unsupported invocation")
    return _read_git_index_paths(repo_root)


def parse_rust_version(value: str) -> tuple[int, int, int] | None:
    """Parse a rust-version or toolchain channel into a comparable triple."""
    match = VERSION_RE.fullmatch(value.strip())
    if match is None:
        return None
    return (int(match.group(1)), int(match.group(2)), int(match.group(3) or 0))


def _nested(document: dict[str, Any], path: str) -> Any:
    """Return a dotted TOML value, or None when any segment is absent."""
    value: Any = document
    for segment in path.split("."):
        if not isinstance(value, dict) or segment not in value:
            return None
        value = value[segment]
    return value


def read_toml(path: Path) -> dict[str, Any]:
    """Load one TOML document as a mapping."""
    document = tomllib.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} must contain a TOML table")
    return document


def toolchain_channel(repo_root: Path) -> str | None:
    """Return the rustup channel declared by rust-toolchain files, if any."""
    toml_path = repo_root / "rust-toolchain.toml"
    if toml_path.is_file() and not toml_path.is_symlink():
        channel = _nested(read_toml(toml_path), "toolchain.channel")
        if isinstance(channel, str) and CHANNEL_RE.fullmatch(channel):
            return channel
    legacy = repo_root / "rust-toolchain"
    if legacy.is_file() and not legacy.is_symlink():
        channel = legacy.read_text(encoding="utf-8").strip().splitlines()[0].strip()
        if CHANNEL_RE.fullmatch(channel):
            return channel
    return None


def declared_rust_version(repo_root: Path) -> str | None:
    """Return package or workspace rust-version from the root Cargo.toml."""
    manifest = repo_root / "Cargo.toml"
    if not manifest.is_file() or manifest.is_symlink():
        return None
    document = read_toml(manifest)
    for path in ("package.rust-version", "workspace.package.rust-version"):
        value = _nested(document, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def rustup_channel(repo_root: Path) -> str | None:
    """Choose the rustup toolchain the coverage image must install."""
    channel = toolchain_channel(repo_root)
    if channel is not None:
        return channel
    rust_version = declared_rust_version(repo_root)
    if rust_version is None:
        return None
    parsed = parse_rust_version(rust_version)
    if parsed is None or parsed <= DEBIAN_RUSTC:
        return None
    return rust_version


def _bounded_member_path(member: str) -> PurePosixPath:
    """Reject absolute or parent-directory workspace member paths."""
    relative = PurePosixPath(member)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"workspace member is not a bounded path: {member}")
    return relative


def expand_workspace_member(repo_root: Path, member: str) -> list[str]:
    """Expand one workspace member or a single trailing ``dir/*`` glob."""
    if any(marker in member for marker in ("?", "[", "**")):
        raise ValueError(f"unsupported workspace member glob: {member}")
    if member.endswith("/*"):
        parent = _bounded_member_path(member[:-2])
        directory = repo_root / parent
        if directory.is_symlink() or not directory.is_dir():
            return []
        paths: list[str] = []
        for child in sorted(directory.iterdir()):
            if child.is_symlink() or not child.is_dir():
                continue
            manifest = child / "Cargo.toml"
            if manifest.is_file() and not manifest.is_symlink():
                paths.append(f"{parent.as_posix()}/{child.name}/Cargo.toml")
        return paths
    if "*" in member:
        raise ValueError(f"unsupported workspace member glob: {member}")
    relative = _bounded_member_path(member)
    member_manifest = f"{relative.as_posix()}/Cargo.toml"
    candidate = repo_root / member_manifest
    if candidate.is_file() and not candidate.is_symlink():
        return [member_manifest]
    return []


def workspace_member_manifests(repo_root: Path) -> list[str]:
    """Return bounded workspace member Cargo.toml paths from the root manifest."""
    manifest = repo_root / "Cargo.toml"
    if not manifest.is_file() or manifest.is_symlink():
        return []
    members = _nested(read_toml(manifest), "workspace.members")
    if not isinstance(members, list):
        return []
    paths: list[str] = []
    for member in members:
        if not isinstance(member, str):
            continue
        paths.extend(expand_workspace_member(repo_root, member))
    return list(dict.fromkeys(paths))


def tracked_paths(repo_root: Path) -> set[str]:
    """Return tracked repository paths from the materialized merge tree."""
    listed = _git(repo_root, "ls-files", "-z").split(b"\0")
    paths: set[str] = set()
    for raw in listed:
        if not raw:
            continue
        path = raw.decode("utf-8", errors="surrogateescape")
        candidate = PurePosixPath(path)
        if not candidate.is_absolute() and ".." not in candidate.parts:
            paths.add(path)
    return paths


def tracked_rust_inputs(repo_root: Path) -> list[str]:
    """List root and workspace Rust manifests that may enter the image context."""
    if not (repo_root / "Cargo.toml").is_file():
        return []
    tracked = tracked_paths(repo_root)
    paths = [name for name in RUST_INPUT_NAMES if name in tracked]
    paths.extend(member for member in workspace_member_manifests(repo_root) if member in tracked)
    return list(dict.fromkeys(paths))


def copy_bounded_file(repo_root: Path, relative: str, output_dir: Path) -> None:
    """Copy one regular, non-symlink repository file into the build context."""
    source = repo_root / relative
    if source.is_symlink() or not source.is_file():
        raise ValueError(f"refusing to materialize non-regular Rust input: {relative}")
    destination = output_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination, follow_symlinks=False)
    destination.chmod(0o444)


def materialize(repo_root: Path, output_dir: Path) -> dict[str, Any]:
    """Write bounded Rust toolchain inputs and a machine-readable manifest."""
    repo_root = repo_root.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    inputs = tracked_rust_inputs(repo_root)
    for relative in inputs:
        copy_bounded_file(repo_root, relative, output_dir)
    payload = {
        "rustup_channel": rustup_channel(repo_root) if inputs else None,
        "has_lock": "Cargo.lock" in inputs,
        "has_manifest": "Cargo.toml" in inputs,
        "inputs": inputs,
    }
    manifest = output_dir / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    manifest.chmod(0o444)
    return payload


def main(argv: list[str] | None = None) -> int:
    """Copy Rust coverage inputs from the merge tree into the image build context."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = materialize(args.repo_root, args.output_dir)
    except (OSError, RuntimeError, ValueError, tomllib.TOMLDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
