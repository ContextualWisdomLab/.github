#!/usr/bin/env python3
"""Materialize hash-pinned Python locks from a validated pull-request base commit."""

from __future__ import annotations

import argparse
import fnmatch
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
UV_EXPORT_TIMEOUT_SECONDS = 120


def _is_candidate_lock_name(name: str) -> bool:
    """Return whether a file name is a possible pip requirements lock."""
    return name == "requirements.lock" or (
        fnmatch.fnmatch(name, "requirements*.txt")
        and not fnmatch.fnmatch(name, "requirements-*-ci-hashes.txt")
    )


def _requirement_lines(content: bytes) -> list[str]:
    """Return logical requirement lines, joining backslash line-continuations.

    ``pip-compile``/``uv export`` write each requirement as a spec line ending in
    a backslash followed by indented ``--hash=`` continuation lines. Joining the
    continuations first keeps a spec and its hashes on one logical line so the
    hash-pin check sees them together.
    """
    text = content.decode("utf-8", errors="ignore").replace("\r\n", "\n")
    joined = text.replace("\\\n", " ")
    lines: list[str] = []
    for raw_line in joined.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _is_hash_pinned(content: bytes) -> bool:
    """Return whether content carries hash pins and is safe to preflight.

    Discovery is content-based rather than name-based so hash-pinned locks in any
    location (a service subdirectory, ``requirements-dev.txt``,
    ``requirements-test.txt``) can be considered for offline coverage, while an
    unpinned or PR-mutable requirements file is still excluded from the networked
    build context. Hash syntax cannot prove that a file includes every transitive
    dependency, so the trusted image installer separately preflights every
    candidate as an independent ``--require-hashes`` closure. An empty file
    carries no installable dependency and is not materialized.
    """
    lines = _requirement_lines(content)
    if not lines:
        return False
    return any(line == "--require-hashes" for line in lines) or all(
        "--hash=" in line or line.startswith(("-r ", "--requirement "))
        for line in lines
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


def _run_uv_export(
    work_dir: pathlib.Path,
    uv_path: str,
    *,
    timeout: float = UV_EXPORT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``uv export`` for a reconstructed base project and return the result.

    ``--frozen`` forbids lock mutation and ``--offline`` forbids network access,
    so the export is a pure function of the already-trusted base ``uv.lock`` and
    ``pyproject.toml``; ``--no-emit-project``/``--no-editable`` drop the project
    itself (installed via ``PYTHONPATH`` in the sandbox) and keep only its
    hash-pinned dependency closure.
    """
    return subprocess.run(
        [
            uv_path,
            "export",
            "--frozen",
            "--offline",
            "--no-emit-project",
            "--no-editable",
            "--format",
            "requirements-txt",
        ],
        cwd=str(work_dir),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _export_uv_lock(
    repo_root: pathlib.Path, base_sha: str, lock_path: str
) -> bytes | None:
    """Export a base ``uv.lock`` to a hash-pinned requirements closure, or ``None``.

    ``uv.lock`` is not a pip-installable format, so a uv-managed repository
    materializes no dependencies and its offline coverage run fails at import.
    When ``uv`` is available, reconstruct the exact base ``uv.lock`` and its
    sibling ``pyproject.toml`` in an isolated temporary directory and run
    ``uv export --frozen`` to produce a fully hash-pinned closure the trusted
    installer can consume like any other lock. Both inputs are read only from
    the validated base commit, so no PR-mutable content reaches ``uv``. Return
    ``None`` — degrading to the prior no-uv behavior — when ``uv`` is absent,
    the sibling ``pyproject.toml`` is missing at the base commit, the export
    fails, or its output is not fully hash-pinned, so this can never break an
    otherwise-working build.
    """
    uv_path = shutil.which("uv")
    if uv_path is None:
        return None
    project_dir = pathlib.PurePosixPath(lock_path).parent
    pyproject_path = (
        "pyproject.toml"
        if str(project_dir) == "."
        else f"{project_dir}/pyproject.toml"
    )
    try:
        lock_content = _git(repo_root, "show", f"{base_sha}:{lock_path}")
        pyproject_content = _git(repo_root, "show", f"{base_sha}:{pyproject_path}")
    except RuntimeError:
        return None
    with tempfile.TemporaryDirectory() as work_dir:
        work_path = pathlib.Path(work_dir)
        (work_path / "uv.lock").write_bytes(lock_content)
        (work_path / "pyproject.toml").write_bytes(pyproject_content)
        try:
            completed = _run_uv_export(work_path, uv_path)
        except (OSError, subprocess.TimeoutExpired):
            return None
    if completed.returncode != 0:
        return None
    exported = completed.stdout
    return exported if _is_hash_pinned(exported) else None


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
        ):
            continue
        if _is_candidate_lock_name(candidate.name):
            content = _git(repo_root, "show", f"{base_sha}:{path}")
            if _is_hash_pinned(content):
                locks.append((path, content))
        elif candidate.name == "uv.lock":
            exported = _export_uv_lock(repo_root, base_sha, path)
            if exported is not None:
                locks.append((path, exported))
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
            "No tracked hash-bearing Python requirement candidates exist at the validated base SHA."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
