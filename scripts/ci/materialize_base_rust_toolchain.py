"""Materialize bounded Rust inputs from a validated pull-request base commit.

The isolated coverage sandbox is networkless and previously used Debian rustc
1.85 without ``llvm-tools-preview``. OriginWeave-style workspaces declare
``rust-version = "1.97"`` and ``edition = "2024"``, so the image must install
the repository toolchain plus llvm-tools and prefetch ``Cargo.lock`` crates
before the sandbox starts. Only regular blobs from the exact validated base
commit may enter that trusted image build context.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by Python 3.10 CI.
    import tomli as tomllib

DEBIAN_RUSTC = (1, 85, 0)
CHANNEL_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
VERSION_RE = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?$")
RUST_INPUT_NAMES = ("rust-toolchain.toml", "rust-toolchain", "Cargo.toml", "Cargo.lock")
REGULAR_BLOB_MODES = frozenset({"100644", "100755"})
GIT_BINARY = "/usr/bin/git"
GIT_TIMEOUT_SECONDS = 30


def _resolve_git_dir(repo_root: Path) -> Path:
    """Return the git directory for a regular checkout or gitdir pointer file."""
    git_path = repo_root / ".git"
    if git_path.is_symlink():
        raise RuntimeError("git object read failed: .git is a symbolic link")
    if git_path.is_file():
        match = re.search(
            r"(?m)^gitdir:\s*(.+?)\s*$",
            git_path.read_text(encoding="utf-8"),
        )
        if match is None:
            raise RuntimeError("git object read failed: invalid gitdir pointer")
        raw = match.group(1)
        candidate = Path(raw) if Path(raw).is_absolute() else git_path.parent / raw
        if candidate.is_symlink() or not candidate.is_dir():
            raise RuntimeError("git object read failed: gitdir is not a regular directory")
        return candidate
    if git_path.is_dir():
        return git_path
    raise RuntimeError("git object read failed: not a git repository")


def _bounded_repo_path(path: str) -> PurePosixPath:
    """Return one normalized repository path or fail closed."""
    candidate = PurePosixPath(path)
    if (
        not path
        or candidate.is_absolute()
        or "." in candidate.parts
        or ".." in candidate.parts
        or "\\" in path
        or "\0" in path
        or candidate.as_posix() != path
    ):
        raise ValueError(f"Rust input is not a bounded repository path: {path!r}")
    return candidate


def _git_environment() -> dict[str, str]:
    """Return a deterministic environment for read-only Git object access."""
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "HOME": os.devnull,
        "LC_ALL": "C",
        "PATH": os.defpath,
    }


def _git(repo_root: Path, *args: str) -> bytes:
    """Run one allowlisted, read-only Git object query."""
    if args[:3] == ("ls-tree", "-rz", "--full-tree") and len(args) == 4:
        if SHA_RE.fullmatch(args[3]) is None:
            raise ValueError("base SHA must be exactly 40 hexadecimal characters")
    elif args[:1] == ("show",) and len(args) == 2:
        revision, separator, path = args[1].partition(":")
        if separator != ":" or SHA_RE.fullmatch(revision) is None or ":" in path:
            raise ValueError("Git blob selector must bind one exact SHA and bounded path")
        _bounded_repo_path(path)
    else:
        raise RuntimeError(
            f"git {args[0] if args else 'command'} failed: unsupported invocation"
        )

    _resolve_git_dir(repo_root)
    completed = subprocess.run(
        [
            GIT_BINARY,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo_root),
            *args,
        ],
        check=False,
        capture_output=True,
        env=_git_environment(),
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"git {args[0]} failed: {stderr}")
    return completed.stdout


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


def read_toml(content: bytes, source: str) -> dict[str, Any]:
    """Load one exact-revision TOML blob as a mapping."""
    document = tomllib.loads(content.decode("utf-8"))
    if not isinstance(document, dict):
        raise TypeError(f"{source} must contain a TOML table")
    return document


def tracked_paths(repo_root: Path, revision_sha: str) -> set[str]:
    """Return regular blob paths from one exact commit tree."""
    if SHA_RE.fullmatch(revision_sha) is None:
        raise ValueError("base SHA must be exactly 40 hexadecimal characters")
    listed = _git(repo_root, "ls-tree", "-rz", "--full-tree", revision_sha)
    paths: set[str] = set()
    for entry in listed.split(b"\0"):
        if not entry:
            continue
        header, separator, raw_path = entry.partition(b"\t")
        fields = header.split()
        if separator != b"\t" or len(fields) != 3:
            raise RuntimeError("git ls-tree failed: malformed tree entry")
        mode, object_type, object_sha = fields
        if len(object_sha) != 40 or re.fullmatch(rb"[0-9a-f]{40}", object_sha) is None:
            raise RuntimeError("git ls-tree failed: invalid object identity")
        if object_type != b"blob" or mode.decode("ascii") not in REGULAR_BLOB_MODES:
            continue
        try:
            path = raw_path.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ValueError("Rust input path is not valid UTF-8") from exc
        _bounded_repo_path(path)
        paths.add(path)
    return paths


def _read_blob(
    repo_root: Path,
    revision_sha: str,
    relative: str,
    regular_paths: set[str],
) -> bytes:
    """Read one proven regular blob from an exact commit tree."""
    _bounded_repo_path(relative)
    if relative not in regular_paths:
        raise ValueError(f"refusing to materialize non-regular Rust input: {relative}")
    return _git(repo_root, "show", f"{revision_sha}:{relative}")


def toolchain_channel(
    repo_root: Path,
    revision_sha: str,
    regular_paths: set[str] | None = None,
) -> str | None:
    """Return the rustup channel declared by exact-revision toolchain files."""
    paths = regular_paths if regular_paths is not None else tracked_paths(repo_root, revision_sha)
    if "rust-toolchain.toml" in paths:
        content = _read_blob(repo_root, revision_sha, "rust-toolchain.toml", paths)
        channel = _nested(read_toml(content, "rust-toolchain.toml"), "toolchain.channel")
        if isinstance(channel, str) and CHANNEL_RE.fullmatch(channel):
            return channel
    if "rust-toolchain" in paths:
        content = _read_blob(repo_root, revision_sha, "rust-toolchain", paths)
        lines = content.decode("utf-8").strip().splitlines()
        if lines:
            channel = lines[0].strip()
            if CHANNEL_RE.fullmatch(channel):
                return channel
    return None


def declared_rust_version(
    repo_root: Path,
    revision_sha: str,
    regular_paths: set[str] | None = None,
) -> str | None:
    """Return package or workspace rust-version from the exact root manifest."""
    paths = regular_paths if regular_paths is not None else tracked_paths(repo_root, revision_sha)
    if "Cargo.toml" not in paths:
        return None
    content = _read_blob(repo_root, revision_sha, "Cargo.toml", paths)
    document = read_toml(content, "Cargo.toml")
    for path in ("package.rust-version", "workspace.package.rust-version"):
        value = _nested(document, path)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def rustup_channel(
    repo_root: Path,
    revision_sha: str,
    regular_paths: set[str] | None = None,
) -> str | None:
    """Choose the rustup toolchain the coverage image must install."""
    paths = regular_paths if regular_paths is not None else tracked_paths(repo_root, revision_sha)
    channel = toolchain_channel(repo_root, revision_sha, paths)
    if channel is not None:
        return channel
    rust_version = declared_rust_version(repo_root, revision_sha, paths)
    if rust_version is None:
        return None
    parsed = parse_rust_version(rust_version)
    if parsed is None or parsed <= DEBIAN_RUSTC:
        return None
    return rust_version


def _bounded_member_path(member: str) -> PurePosixPath:
    """Reject absolute or parent-directory workspace member paths."""
    return _bounded_repo_path(member)


def expand_workspace_member(member: str, regular_paths: set[str]) -> list[str]:
    """Expand one workspace member against exact-tree regular blob paths."""
    if any(marker in member for marker in ("?", "[", "**")):
        raise ValueError(f"unsupported workspace member glob: {member}")
    if member.endswith("/*"):
        parent = _bounded_member_path(member[:-2])
        prefix = f"{parent.as_posix()}/"
        paths: list[str] = []
        for path in sorted(regular_paths):
            if not path.startswith(prefix) or not path.endswith("/Cargo.toml"):
                continue
            remainder = path[len(prefix) :]
            if remainder.count("/") == 1:
                paths.append(path)
        return paths
    if "*" in member:
        raise ValueError(f"unsupported workspace member glob: {member}")
    relative = _bounded_member_path(member)
    member_manifest = f"{relative.as_posix()}/Cargo.toml"
    return [member_manifest] if member_manifest in regular_paths else []


def workspace_member_manifests(
    repo_root: Path,
    revision_sha: str,
    regular_paths: set[str] | None = None,
) -> list[str]:
    """Return bounded workspace member manifests from one exact root manifest."""
    paths = regular_paths if regular_paths is not None else tracked_paths(repo_root, revision_sha)
    if "Cargo.toml" not in paths:
        return []
    content = _read_blob(repo_root, revision_sha, "Cargo.toml", paths)
    members = _nested(read_toml(content, "Cargo.toml"), "workspace.members")
    if not isinstance(members, list):
        return []
    manifests: list[str] = []
    for member in members:
        if isinstance(member, str):
            manifests.extend(expand_workspace_member(member, paths))
    return list(dict.fromkeys(manifests))


def tracked_rust_inputs(
    repo_root: Path,
    revision_sha: str,
    regular_paths: set[str] | None = None,
) -> list[str]:
    """List exact-revision Rust inputs that may enter the image context."""
    paths = regular_paths if regular_paths is not None else tracked_paths(repo_root, revision_sha)
    if "Cargo.toml" not in paths:
        return []
    inputs = [name for name in RUST_INPUT_NAMES if name in paths]
    inputs.extend(workspace_member_manifests(repo_root, revision_sha, paths))
    return list(dict.fromkeys(inputs))


def write_bounded_blob(
    repo_root: Path,
    revision_sha: str,
    relative: str,
    regular_paths: set[str],
    output_dir: Path,
) -> None:
    """Write one exact-revision regular blob into the build context."""
    content = _read_blob(repo_root, revision_sha, relative, regular_paths)
    destination = output_dir / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError(f"refusing to replace symlinked Rust output: {relative}")
    destination.write_bytes(content)
    destination.chmod(0o444)


def materialize(repo_root: Path, base_sha: str, output_dir: Path) -> dict[str, Any]:
    """Write bounded Rust inputs and a revision-bound machine-readable manifest."""
    if SHA_RE.fullmatch(base_sha) is None:
        raise ValueError("base SHA must be exactly 40 hexadecimal characters")
    repo_root = repo_root.resolve()
    if output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = tracked_paths(repo_root, base_sha)
    inputs = tracked_rust_inputs(repo_root, base_sha, paths)
    for relative in inputs:
        write_bounded_blob(repo_root, base_sha, relative, paths, output_dir)
    payload = {
        "revision_sha": base_sha.lower(),
        "rustup_channel": rustup_channel(repo_root, base_sha, paths) if inputs else None,
        "has_lock": "Cargo.lock" in inputs,
        "has_manifest": "Cargo.toml" in inputs,
        "inputs": inputs,
    }
    manifest = output_dir / "manifest.json"
    manifest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    manifest.chmod(0o444)
    return payload


def main(argv: list[str] | None = None) -> int:
    """Copy Rust coverage inputs from an exact base commit into the image context."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        payload = materialize(args.repo_root, args.base_sha, args.output_dir)
    except (
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        UnicodeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
