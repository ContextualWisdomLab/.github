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
from typing import Any


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
PNPM_SPEC_RE = re.compile(r"^pnpm@[0-9]+\.[0-9]+\.[0-9]+(?:[+-][A-Za-z0-9._+-]+)?$")
PNPM_BASE_INPUT_NAMES = ("package.json", "pnpm-workspace.yaml", ".pnpmfile.cjs")
NPM_LOCK_NAMES = ("npm-shrinkwrap.json", "package-lock.json")


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
            if str(project_root / "package-lock.json") in regular_paths:
                # A sibling package-lock.json means npm owns this project and
                # the pnpm-lock.yaml is a vestigial second lockfile. Skip pnpm
                # materialization so the downstream npm (package-lock.json)
                # install path handles it, instead of failing the whole
                # coverage-evidence job. A genuine pnpm-only project (no sibling
                # package-lock.json) still must pin an exact pnpm packageManager.
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
            raise ValueError(
                f"trusted base npm lock {lock_path} must be a JSON object"
            )

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


def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
) -> list[dict[str, str]]:
    """Write base JavaScript package inputs under Docker-context-safe paths."""
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, str]] = []
    projects = base_pnpm_projects(repo_root, base_sha) + base_npm_projects(
        repo_root, base_sha
    )
    for index, (source_path, package_manager, base_inputs) in enumerate(
        sorted(projects, key=lambda project: project[0])
    ):
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
                "package_manager": package_manager,
                "source": source_path,
            }
        )

    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Materialize base JavaScript locks and report the trusted inputs."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)

    try:
        manifest = materialize(args.repo_root, args.base_sha, args.output_dir)
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            f"::error::Could not materialize base JavaScript package locks: {exc}",
            file=sys.stderr,
        )
        return 1

    if manifest:
        for entry in manifest:
            print(
                "Materialized trusted base JavaScript lock "
                f"{entry['source']} for {entry['package_manager']} "
                f"as {entry['directory']}/{pathlib.PurePosixPath(entry['source']).name}."
            )
    else:
        print(
            "No tracked supported JavaScript package lockfiles exist "
            "at the validated base SHA."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
