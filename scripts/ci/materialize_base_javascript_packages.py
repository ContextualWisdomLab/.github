#!/usr/bin/env python3
"""Materialize pnpm locks from a validated pull-request base commit.

A ``pnpm-lock.yaml`` whose sibling ``package.json`` does not pin an exact pnpm
``packageManager`` is treated as a genuine pnpm project only when no sibling
``package-lock.json`` exists; otherwise it is a vestigial second lockfile in an
npm-managed project and is skipped so the downstream npm install path handles it
instead of failing coverage evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import stat
import subprocess
import sys
import urllib.parse
from typing import Any


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
PNPM_SPEC_RE = re.compile(r"^pnpm@[0-9]+\.[0-9]+\.[0-9]+(?:[+-][A-Za-z0-9._+-]+)?$")
PNPM_BASE_INPUT_NAMES = ("package.json", "pnpm-workspace.yaml", ".pnpmfile.cjs")
NPM_LOCK_NAMES = ("npm-shrinkwrap.json", "package-lock.json")
NPM_REGISTRY_HOST = "registry.npmjs.org"
SHA512_SRI_RE = re.compile(r"^sha512-[A-Za-z0-9+/]{86}==$")
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
_NEW_FILE_FLAGS = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW


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


def _regular_base_paths(repo_root: pathlib.Path, base_sha: str) -> set[str]:
    """Return regular blob paths from the exact validated base commit."""
    entries = _git(repo_root, "ls-tree", "-r", "-z", "--full-tree", base_sha)
    paths: set[str] = set()
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
            object_type == "blob"
            and mode.startswith("100")
            and not candidate.is_absolute()
            and ".." not in candidate.parts
        ):
            paths.add(path)
    return paths


def base_pnpm_projects(
    repo_root: pathlib.Path, base_sha: str
) -> list[tuple[str, str, dict[str, bytes]]]:
    """Return exact base pnpm inputs grouped by lockfile directory."""
    if not SHA_RE.fullmatch(base_sha):
        raise ValueError("base SHA must be exactly 40 hexadecimal characters")

    repo_root = repo_root.resolve()
    regular_paths = _regular_base_paths(repo_root, base_sha)
    projects: list[tuple[str, str, dict[str, bytes]]] = []
    for lock_path in sorted(
        path
        for path in regular_paths
        if pathlib.PurePosixPath(path).name == "pnpm-lock.yaml"
    ):
        lock = pathlib.PurePosixPath(lock_path)
        project_root = lock.parent
        package_path = str(project_root / "package.json")
        if package_path not in regular_paths:
            raise ValueError(
                f"trusted base pnpm lock {lock_path} has no regular sibling package.json"
            )
        try:
            package_data: Any = json.loads(
                _git(repo_root, "show", f"{base_sha}:{package_path}").decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"trusted base package manifest {package_path} is invalid JSON: {exc}"
            ) from exc
        if not isinstance(package_data, dict):
            raise ValueError(
                f"trusted base package manifest {package_path} must be a JSON object"
            )
        package_manager = package_data.get("packageManager")
        if not isinstance(package_manager, str) or not PNPM_SPEC_RE.fullmatch(
            package_manager
        ):
            if any(
                str(project_root / lock_name) in regular_paths
                for lock_name in NPM_LOCK_NAMES
            ):
                continue
            raise ValueError(
                f"trusted base package manifest {package_path} must declare an exact pnpm packageManager version"
            )
        lock_content = _git(repo_root, "show", f"{base_sha}:{lock_path}")
        if not lock_content.strip():
            raise ValueError(f"trusted base pnpm lock {lock_path} is empty")

        base_inputs = {
            input_name: _git(
                repo_root,
                "show",
                f"{base_sha}:{project_root / input_name}",
            )
            for input_name in PNPM_BASE_INPUT_NAMES
            if str(project_root / input_name) in regular_paths
        }
        base_inputs["pnpm-lock.yaml"] = lock_content

        patches_root = project_root / "patches"
        for base_path in sorted(regular_paths):
            candidate = pathlib.PurePosixPath(base_path)
            if candidate == patches_root or patches_root not in candidate.parents:
                continue
            relative_path = str(candidate.relative_to(project_root))
            base_inputs[relative_path] = _git(
                repo_root, "show", f"{base_sha}:{base_path}"
            )

        projects.append((lock_path, package_manager, base_inputs))
    return projects


def base_npm_projects(
    repo_root: pathlib.Path, base_sha: str
) -> list[tuple[str, str, dict[str, bytes]]]:
    """Return exact base npm inputs grouped by lockfile directory."""
    if not SHA_RE.fullmatch(base_sha):
        raise ValueError("base SHA must be exactly 40 hexadecimal characters")

    repo_root = repo_root.resolve()
    regular_paths = _regular_base_paths(repo_root, base_sha)
    lock_by_project: dict[pathlib.PurePosixPath, pathlib.PurePosixPath] = {}
    for lock_name in NPM_LOCK_NAMES:
        for lock_path in sorted(
            path
            for path in regular_paths
            if pathlib.PurePosixPath(path).name == lock_name
        ):
            lock = pathlib.PurePosixPath(lock_path)
            lock_by_project.setdefault(lock.parent, lock)

    projects: list[tuple[str, str, dict[str, bytes]]] = []
    for project_root, lock in sorted(
        lock_by_project.items(), key=lambda item: str(item[1])
    ):
        lock_path = str(lock)
        package_path = str(project_root / "package.json")
        if package_path not in regular_paths:
            raise ValueError(
                f"trusted base npm lock {lock_path} has no regular sibling package.json"
            )
        try:
            package_data: Any = json.loads(
                _git(repo_root, "show", f"{base_sha}:{package_path}").decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"trusted base package manifest {package_path} is invalid JSON: {exc}"
            ) from exc
        if not isinstance(package_data, dict):
            raise ValueError(
                f"trusted base package manifest {package_path} must be a JSON object"
            )
        package_manager = package_data.get("packageManager")
        if isinstance(package_manager, str) and PNPM_SPEC_RE.fullmatch(package_manager):
            continue

        lock_content = _git(repo_root, "show", f"{base_sha}:{lock_path}")
        if not lock_content.strip():
            raise ValueError(f"trusted base npm lock {lock_path} is empty")
        try:
            lock_data: Any = json.loads(lock_content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"trusted base npm lock {lock_path} is invalid JSON: {exc}"
            ) from exc
        if not isinstance(lock_data, dict):
            raise ValueError(f"trusted base npm lock {lock_path} must be a JSON object")

        base_inputs = {
            "package.json": _git(repo_root, "show", f"{base_sha}:{package_path}"),
            lock.name: lock_content,
        }
        lock_packages = lock_data.get("packages")
        if isinstance(lock_packages, dict):
            for workspace_path in sorted(lock_packages):
                workspace = pathlib.PurePosixPath(str(workspace_path))
                if (
                    not workspace_path
                    or workspace.is_absolute()
                    or ".." in workspace.parts
                    or "node_modules" in workspace.parts
                ):
                    continue
                workspace_package = project_root / workspace / "package.json"
                workspace_package_path = str(workspace_package)
                if workspace_package_path in regular_paths:
                    base_inputs[str(workspace / "package.json")] = _git(
                        repo_root,
                        "show",
                        f"{base_sha}:{workspace_package_path}",
                    )

        projects.append((lock_path, "npm", base_inputs))
    return projects


def _lock_blob_sha(repo_root: pathlib.Path, revision_sha: str, lock_path: str) -> str:
    """Return the exact Git blob SHA for one validated revision lockfile."""
    raw_blob = _git(repo_root, "rev-parse", f"{revision_sha}:{lock_path}")
    blob_sha = raw_blob.decode("ascii", errors="strict").strip()
    if not SHA_RE.fullmatch(blob_sha):
        raise RuntimeError(
            f"git rev-parse returned an invalid blob SHA for {lock_path}"
        )
    return blob_sha.lower()


def _npm_package_identity(
    lock_path: str,
    package_path: str,
    candidate: pathlib.PurePosixPath,
) -> str:
    """Return the exact npm identity after the final ``node_modules`` segment."""
    final_node_modules = max(
        index for index, part in enumerate(candidate.parts) if part == "node_modules"
    )
    identity_parts = candidate.parts[final_node_modules + 1 :]
    if (
        len(identity_parts) == 1
        and identity_parts[0]
        and not identity_parts[0].startswith("@")
    ):
        return identity_parts[0]
    if (
        len(identity_parts) == 2
        and identity_parts[0].startswith("@")
        and len(identity_parts[0]) > 1
        and identity_parts[1]
        and not identity_parts[1].startswith("@")
    ):
        return "/".join(identity_parts)
    raise ValueError(
        f"current-head npm lock {lock_path} package {package_path} has a malformed npm package identity"
    )


def _validate_npm_registry_pin(
    lock_path: str,
    package_path: str,
    resolved: Any,
    integrity: Any,
) -> None:
    """Validate one exact public-registry tarball and SHA-512 integrity pair."""
    if not isinstance(resolved, str) or not isinstance(integrity, str):
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} must pin a registry tarball and SHA-512 integrity"
        )
    parsed = urllib.parse.urlsplit(resolved)
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} has an invalid registry URL"
        ) from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != NPM_REGISTRY_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed_port is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/")
        or not parsed.path.endswith(".tgz")
    ):
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} must resolve from https://{NPM_REGISTRY_HOST}/"
        )
    if not SHA512_SRI_RE.fullmatch(integrity):
        raise ValueError(
            f"current-head npm lock {lock_path} package {package_path} must use one SHA-512 integrity value"
        )


def validate_head_npm_lock(lock_path: str, lock_content: bytes) -> None:
    """Fail closed unless a changed HEAD npm lock is registry- and hash-bounded."""
    try:
        lock_data: Any = json.loads(lock_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"current-head npm lock {lock_path} is invalid JSON: {exc}"
        ) from exc
    if not isinstance(lock_data, dict):
        raise ValueError(f"current-head npm lock {lock_path} must be a JSON object")
    lockfile_version = lock_data.get("lockfileVersion")
    if (
        not isinstance(lockfile_version, int)
        or isinstance(lockfile_version, bool)
        or lockfile_version not in (2, 3)
    ):
        raise ValueError(
            f"current-head npm lock {lock_path} must use lockfileVersion 2 or 3"
        )
    packages = lock_data.get("packages")
    if not isinstance(packages, dict):
        raise ValueError(
            f"current-head npm lock {lock_path} must contain an object-valued packages map"
        )

    canonical_versions: dict[str, str] = {}
    metadata_only_locations: list[tuple[str, str, str]] = []
    for package_path, metadata in sorted(packages.items()):
        if not isinstance(package_path, str) or not isinstance(metadata, dict):
            raise ValueError(
                f"current-head npm lock {lock_path} contains malformed package metadata"
            )
        if "\\" in package_path:
            raise ValueError(
                f"current-head npm lock {lock_path} contains unsafe package path {package_path!r}"
            )
        candidate = pathlib.PurePosixPath(package_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            raise ValueError(
                f"current-head npm lock {lock_path} contains unsafe package path {package_path!r}"
            )
        if not package_path or "node_modules" not in candidate.parts:
            continue

        identity = _npm_package_identity(lock_path, package_path, candidate)
        resolved = metadata.get("resolved")
        if metadata.get("link") is True:
            if not isinstance(resolved, str) or not resolved or "\\" in resolved:
                raise ValueError(
                    f"current-head npm lock {lock_path} contains an unsafe workspace link for {package_path}"
                )
            link_target = pathlib.PurePosixPath(resolved)
            if (
                link_target.is_absolute()
                or ".." in link_target.parts
                or "node_modules" in link_target.parts
            ):
                raise ValueError(
                    f"current-head npm lock {lock_path} contains an unsafe workspace link for {package_path}"
                )
            continue

        has_resolved = "resolved" in metadata
        has_integrity = "integrity" in metadata
        if has_resolved != has_integrity:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must not partially declare a registry tarball and SHA-512 integrity"
            )
        if has_resolved:
            _validate_npm_registry_pin(
                lock_path,
                package_path,
                metadata.get("resolved"),
                metadata.get("integrity"),
            )

        version = metadata.get("version")
        canonical_path = f"node_modules/{identity}"
        is_canonical_root = package_path == canonical_path
        if not isinstance(version, str) or not version:
            if is_canonical_root and not has_resolved:
                raise ValueError(
                    f"current-head npm lock {lock_path} package {package_path} must pin a registry tarball and SHA-512 integrity"
                )
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must declare a nonempty exact version"
            )

        if has_resolved:
            if is_canonical_root:
                canonical_versions[identity] = version
            continue

        if is_canonical_root:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must be a complete canonical root pin"
            )
        metadata_only_locations.append((package_path, identity, version))

    for package_path, identity, version in metadata_only_locations:
        canonical_version = canonical_versions.get(identity)
        if canonical_version is None:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} has no complete canonical root pin"
            )
        if canonical_version != version:
            raise ValueError(
                f"current-head npm lock {lock_path} package {package_path} must match the exact canonical version {canonical_version}"
            )


def _reject_symlinked_output_components(output_dir: pathlib.Path) -> None:
    """Reject existing symlink components before materialization writes begin."""
    candidate = output_dir.absolute()
    if candidate == pathlib.Path(candidate.anchor):
        raise ValueError("output directory must not be the filesystem root")
    current = pathlib.Path(candidate.anchor)
    for component in candidate.parts[1:]:
        current /= component
        if current.is_symlink():
            raise ValueError(
                "output directory must not be a symlink; "
                f"path must not contain symlinks: {current}"
            )
        if not current.exists():
            break
        if not current.is_dir():
            raise ValueError(
                f"output directory path component must be a directory: {current}"
            )


def _open_output_directory(output_dir: pathlib.Path) -> tuple[int, tuple[int, int]]:
    """Open one no-follow output directory and return its descriptor identity."""
    candidate = output_dir.absolute()
    _reject_symlinked_output_components(candidate)
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.mkdir(exist_ok=True)
    _reject_symlinked_output_components(candidate)
    parent_fd = os.open(candidate.parent, _DIRECTORY_OPEN_FLAGS)
    try:
        try:
            output_fd = os.open(
                candidate.name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=parent_fd,
            )
        except OSError as exc:
            raise ValueError(
                "output directory must not be a symlink; "
                f"path must not contain symlinks: {candidate}"
            ) from exc
    finally:
        os.close(parent_fd)
    metadata = os.fstat(output_fd)
    return output_fd, (metadata.st_dev, metadata.st_ino)


def _verify_output_directory_binding(
    output_dir: pathlib.Path,
    output_fd: int,
    identity: tuple[int, int],
) -> None:
    """Fail closed if the published output pathname no longer names the opened directory."""
    descriptor_metadata = os.fstat(output_fd)
    try:
        path_metadata = os.stat(output_dir.absolute(), follow_symlinks=False)
    except OSError as exc:
        raise ValueError("output directory changed during secure materialization") from exc
    if (
        not stat.S_ISDIR(path_metadata.st_mode)
        or (descriptor_metadata.st_dev, descriptor_metadata.st_ino) != identity
        or (path_metadata.st_dev, path_metadata.st_ino) != identity
    ):
        raise ValueError("output directory changed during secure materialization")


def _safe_relative_parts(relative_path: str) -> tuple[str, ...]:
    """Return one normalized relative POSIX output path or fail closed."""
    candidate = pathlib.PurePosixPath(relative_path)
    if (
        not relative_path
        or "\\" in relative_path
        or candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != relative_path
        or not candidate.parts
    ):
        raise ValueError(f"unsafe relative output path: {relative_path!r}")
    return candidate.parts


def _open_relative_directory(root_fd: int, parts: tuple[str, ...]) -> int:
    """Open or create trusted child directories relative to one pinned descriptor."""
    current_fd = os.dup(root_fd)
    try:
        for part in parts:
            try:
                os.mkdir(part, mode=0o700, dir_fd=current_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, _DIRECTORY_OPEN_FLAGS, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except BaseException:
        os.close(current_fd)
        raise


def _create_project_directory(output_fd: int, directory: str) -> int:
    """Create a fresh project directory beneath the pinned output descriptor."""
    try:
        os.mkdir(directory, mode=0o700, dir_fd=output_fd)
    except FileExistsError as exc:
        raise ValueError(
            f"generated output path must not pre-exist: {directory}"
        ) from exc
    return os.open(directory, _DIRECTORY_OPEN_FLAGS, dir_fd=output_fd)


def _write_new_file(parent_fd: int, filename: str, content: bytes) -> None:
    """Create, synchronize, and revalidate one descriptor-pinned regular file."""
    try:
        file_fd = os.open(
            filename,
            _NEW_FILE_FLAGS,
            0o600,
            dir_fd=parent_fd,
        )
    except FileExistsError as exc:
        raise ValueError(
            f"generated output file must not pre-exist: {filename}"
        ) from exc
    try:
        initial_metadata = os.fstat(file_fd)
        if not stat.S_ISREG(initial_metadata.st_mode) or initial_metadata.st_nlink != 1:
            raise ValueError(
                "generated output files must be singly linked regular files"
            )
        view = memoryview(content)
        offset = 0
        while offset < len(view):
            written = os.write(file_fd, view[offset:])
            if written <= 0:
                raise OSError("output write made no progress")
            offset += written
        os.fsync(file_fd)
        final_metadata = os.fstat(file_fd)
        path_metadata = os.stat(filename, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(path_metadata.st_mode)
            or (final_metadata.st_dev, final_metadata.st_ino)
            != (path_metadata.st_dev, path_metadata.st_ino)
        ):
            raise ValueError("output file changed during secure materialization")
        if final_metadata.st_nlink != 1 or path_metadata.st_nlink != 1:
            raise ValueError(
                "generated output files must remain singly linked regular files"
            )
    finally:
        os.close(file_fd)


def _write_relative_file(
    project_fd: int,
    relative_path: str,
    content: bytes,
) -> None:
    """Write one validated project-relative input through pinned directories."""
    parts = _safe_relative_parts(relative_path)
    parent_fd = _open_relative_directory(project_fd, tuple(parts[:-1]))
    try:
        _write_new_file(parent_fd, parts[-1], content)
    finally:
        os.close(parent_fd)


def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
    head_sha: str | None = None,
) -> list[dict[str, str]]:
    """Write trusted base and bounded HEAD inputs under Docker-context-safe paths."""
    output_fd, output_identity = _open_output_directory(output_dir)
    try:
        manifest: list[dict[str, str]] = []
        projects: list[tuple[str, str, dict[str, bytes], str, str]] = []
        base_npm = base_npm_projects(repo_root, base_sha)
        base_npm_paths = {source_path for source_path, _manager, _inputs in base_npm}
        base_npm_blobs: dict[str, str] = {}
        for source_path, package_manager, base_inputs in (
            base_pnpm_projects(repo_root, base_sha) + base_npm
        ):
            lock_blob = _lock_blob_sha(repo_root, base_sha, source_path)
            projects.append(
                (
                    source_path,
                    package_manager,
                    base_inputs,
                    base_sha.lower(),
                    lock_blob,
                )
            )
            if source_path in base_npm_paths:
                base_npm_blobs[source_path] = lock_blob

        if head_sha is not None:
            if not SHA_RE.fullmatch(head_sha):
                raise ValueError("head SHA must be exactly 40 hexadecimal characters")
            for source_path, package_manager, head_inputs in base_npm_projects(
                repo_root, head_sha
            ):
                head_blob = _lock_blob_sha(repo_root, head_sha, source_path)
                if base_npm_blobs.get(source_path) == head_blob:
                    continue
                lock_name = pathlib.PurePosixPath(source_path).name
                validate_head_npm_lock(source_path, head_inputs[lock_name])
                projects.append(
                    (
                        source_path,
                        package_manager,
                        head_inputs,
                        head_sha.lower(),
                        head_blob,
                    )
                )

        for index, (
            source_path,
            package_manager,
            base_inputs,
            revision_sha,
            lock_blob,
        ) in enumerate(sorted(projects, key=lambda project: (project[0], project[3]))):
            directory = f"project-{index:03d}"
            project_fd = _create_project_directory(output_fd, directory)
            try:
                for relative_path, content in sorted(base_inputs.items()):
                    _write_relative_file(project_fd, relative_path, content)
            finally:
                os.close(project_fd)
            manifest.append(
                {
                    "directory": directory,
                    "lock_blob": lock_blob,
                    "package_manager": package_manager,
                    "revision_sha": revision_sha,
                    "source": source_path,
                }
            )

        manifest_content = (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_new_file(output_fd, "manifest.json", manifest_content)
        _verify_output_directory_binding(output_dir, output_fd, output_identity)
        return manifest
    finally:
        os.close(output_fd)


def main(argv: list[str] | None = None) -> int:
    """Materialize trusted JavaScript locks and report their exact revisions."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha")
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)

    try:
        manifest = materialize(
            args.repo_root,
            args.base_sha,
            args.output_dir,
            head_sha=args.head_sha,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            f"::error::Could not materialize base JavaScript package locks: {exc}",
            file=sys.stderr,
        )
        return 1

    if manifest:
        for entry in manifest:
            print(
                "Materialized trusted JavaScript lock "
                f"{entry['source']} for {entry['package_manager']} "
                f"from {entry['revision_sha']} as "
                f"{entry['directory']}/{pathlib.PurePosixPath(entry['source']).name}."
            )
    else:
        print(
            "No tracked supported JavaScript package lockfiles exist "
            "at the validated base SHA."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
