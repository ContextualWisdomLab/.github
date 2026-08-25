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
import pathlib
import re
import subprocess
import sys
import urllib.parse
from typing import Any


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
PNPM_SPEC_RE = re.compile(r"^pnpm@[0-9]+\.[0-9]+\.[0-9]+(?:[+-][A-Za-z0-9._+-]+)?$")
PNPM_BASE_INPUT_NAMES = ("package.json", "pnpm-workspace.yaml", ".pnpmfile.cjs")
NPM_LOCK_NAMES = ("npm-shrinkwrap.json", "package-lock.json")
PNPM_LOCK_NAME = "pnpm-lock.yaml"
NPM_REGISTRY_HOST = "registry.npmjs.org"
SHA512_SRI_RE = re.compile(r"^sha512-[A-Za-z0-9+/]{86}==$")
PNPM_PACKAGE_ENTRY_RE = re.compile(r"^  ([^ #][^:]*):(?:\s.*)?$")
PNPM_RESOLUTION_RE = re.compile(r"resolution:\s*\{(.*)\}\s*$")
PNPM_TARBALL_RE = re.compile(r"tarball:\s*([^,\s}]+)")
PNPM_INTEGRITY_RE = re.compile(r"integrity:\s*([^,\s}]+)")
PNPM_DIRECTORY_RE = re.compile(r"directory:\s*\"?([^,\"}]+)\"?")
PNPM_LINK_TRUE_RE = re.compile(r"link:\s*true\b")


def _github_actions_escape(value: object) -> str:
    """Escape untrusted text before writing it to a GitHub Actions log.

    GitHub Actions recognizes workflow commands in log lines. Repository paths
    and git diagnostics can contain command delimiters, newlines, or percent
    escapes when a pull request controls the tree, so diagnostics must never be
    emitted verbatim. The manifest itself remains raw; this helper only protects
    the human-readable CLI output.
    """
    return (
        str(value)
        .replace("%", "%25")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
        .replace(":", "%3A")
    )


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
                # A sibling npm lock means npm owns this project and the
                # pnpm-lock.yaml is a vestigial second lockfile. Skip pnpm
                # materialization so the downstream npm install path handles
                # it, instead of failing the whole coverage-evidence job. A
                # genuine pnpm-only project (no sibling npm lock) still must
                # pin an exact pnpm packageManager.
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
            # An exact pnpm declaration owns this project. A sibling npm lock
            # is vestigial and must not create a second dependency cache.
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

        integrity = metadata.get("integrity")
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


def _validate_pnpm_tarball_url(
    lock_path: str, package_key: str, tarball_url: str
) -> None:
    """Fail closed unless one pnpm tarball URL is an npm-registry HTTPS URL."""
    parsed = urllib.parse.urlsplit(tarball_url)
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError(
            f"current-head pnpm lock {lock_path} package {package_key} has an invalid tarball URL"
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
            f"current-head pnpm lock {lock_path} package {package_key} must resolve from https://{NPM_REGISTRY_HOST}/"
        )


def validate_head_pnpm_lock(lock_path: str, lock_content: bytes) -> None:
    """Fail closed unless a changed HEAD pnpm lock is registry- and hash-bounded.

    The validator is intentionally line-based and standard-library-only: pnpm
    lockfiles always emit each package's ``resolution`` as a single-line inline
    mapping, so scanning those lines covers every fetched artifact while never
    introducing a YAML parser dependency into the trusted materializer.
    """
    try:
        text = lock_content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"current-head pnpm lock {lock_path} is invalid UTF-8: {exc}"
        ) from exc
    if not text.strip():
        raise ValueError(f"current-head pnpm lock {lock_path} is empty")

    in_packages_section = False
    package_entry_count = 0
    current_package_key = ""
    current_resolution_seen = False

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0 and stripped.endswith(":"):
            in_packages_section = stripped == "packages:"
            continue
        if not in_packages_section:
            continue

        if indent == 2:
            entry_match = PNPM_PACKAGE_ENTRY_RE.match(line)
            if entry_match is None:
                raise ValueError(
                    f"current-head pnpm lock {lock_path} contains an unexpected "
                    f"two-space entry {stripped!r}"
                )
            if current_package_key and not current_resolution_seen:
                raise ValueError(
                    f"current-head pnpm lock {lock_path} package {current_package_key} "
                    "has no resolution entry"
                )
            current_package_key = entry_match.group(1).strip()
            package_entry_count += 1
            current_resolution_seen = False
            continue

        if current_package_key and stripped.startswith("resolution:"):
            resolution_match = PNPM_RESOLUTION_RE.search(stripped)
            if resolution_match is None:
                raise ValueError(
                    f"current-head pnpm lock {lock_path} package {current_package_key} "
                    "has a multi-line or malformed resolution mapping"
                )
            resolution_body = resolution_match.group(1)
            integrity_match = PNPM_INTEGRITY_RE.search(resolution_body)
            link_match = PNPM_LINK_TRUE_RE.search(resolution_body)
            directory_match = PNPM_DIRECTORY_RE.search(resolution_body)
            if link_match is not None:
                if directory_match is None:
                    raise ValueError(
                        f"current-head pnpm lock {lock_path} workspace link "
                        f"{current_package_key} must carry a relative directory target"
                    )
                directory_value = directory_match.group(1).strip().strip('"')
                directory_candidate = pathlib.PurePosixPath(directory_value)
                if (
                    directory_candidate.is_absolute()
                    or ".." in directory_candidate.parts
                    or "node_modules" in directory_candidate.parts
                ):
                    raise ValueError(
                        f"current-head pnpm lock {lock_path} workspace link "
                        f"{current_package_key} has an unsafe directory target"
                    )
            elif integrity_match is None or not SHA512_SRI_RE.fullmatch(
                integrity_match.group(1)
            ):
                raise ValueError(
                    f"current-head pnpm lock {lock_path} package {current_package_key} "
                    "must pin exactly one SHA-512 integrity value"
                )
            tarball_match = PNPM_TARBALL_RE.search(resolution_body)
            if tarball_match is not None:
                _validate_pnpm_tarball_url(
                    lock_path, current_package_key, tarball_match.group(1)
                )
            current_resolution_seen = True
            continue

        if current_package_key and (
            stripped.startswith("tarball:") or stripped.startswith("git+")
        ):
            raise ValueError(
                f"current-head pnpm lock {lock_path} package {current_package_key} "
                "carries an out-of-band fetch source"
            )

    if current_package_key and not current_resolution_seen:
        raise ValueError(
            f"current-head pnpm lock {lock_path} package {current_package_key} "
            "has no resolution entry"
        )
    if package_entry_count == 0:
        raise ValueError(
            f"current-head pnpm lock {lock_path} contains no package entries"
        )


def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
    head_sha: str | None = None,
) -> list[dict[str, str]]:
    """Write trusted base and bounded HEAD inputs under Docker-context-safe paths."""
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    projects: list[tuple[str, str, dict[str, bytes], str, str]] = []
    base_npm = base_npm_projects(repo_root, base_sha)
    base_npm_paths = {source_path for source_path, _manager, _inputs in base_npm}
    base_npm_blobs: dict[str, str] = {}
    base_pnpm_blobs: dict[str, str] = {}
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
        else:
            base_pnpm_blobs[source_path] = lock_blob

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
        for source_path, package_manager, head_inputs in base_pnpm_projects(
            repo_root, head_sha
        ):
            head_blob = _lock_blob_sha(repo_root, head_sha, source_path)
            if base_pnpm_blobs.get(source_path) == head_blob:
                continue
            validate_head_pnpm_lock(source_path, head_inputs[PNPM_LOCK_NAME])
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
        project_dir = output_dir / directory
        project_dir.mkdir()
        for relative_path, content in sorted(base_inputs.items()):
            destination = project_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        manifest.append(
            {
                "directory": directory,
                "lock_blob": lock_blob,
                "package_manager": package_manager,
                "revision_sha": revision_sha,
                "source": source_path,
            }
        )

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


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
            "::error::Could not materialize base JavaScript package locks: "
            f"{_github_actions_escape(exc)}",
            file=sys.stderr,
        )
        return 1

    if manifest:
        for entry in manifest:
            print(
                "Materialized trusted JavaScript lock "
                f"{_github_actions_escape(entry['source'])} for "
                f"{_github_actions_escape(entry['package_manager'])} from "
                f"{_github_actions_escape(entry['revision_sha'])} as "
                f"{_github_actions_escape(entry['directory'])}/"
                f"{_github_actions_escape(pathlib.PurePosixPath(entry['source']).name)}."
            )
    else:
        print(
            "No tracked supported JavaScript package lockfiles exist "
            "at the validated base SHA."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
