#!/usr/bin/env python3
"""Materialize hash-pinned Python locks from a validated pull-request base commit."""

from __future__ import annotations

import argparse
import atexit
import fnmatch
import functools
import hashlib
import io
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
UV_EXPORT_TIMEOUT_SECONDS = 120
TRUSTED_UV_VERSION = "0.12.1"
TRUSTED_UV_ARCHIVE_URL = (
    "https://releases.astral.sh/github/uv/releases/download/0.12.1/"
    "uv-x86_64-unknown-linux-gnu.tar.gz"
)
TRUSTED_UV_ARCHIVE_SHA256 = (
    "90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb"
)
TRUSTED_UV_ARCHIVE_MEMBER = "uv-x86_64-unknown-linux-gnu/uv"
TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS = 120
TRUSTED_UV_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024
TRUSTED_UV_BINARY_MAX_BYTES = 64 * 1024 * 1024
TRUSTED_UV_VERSION_TIMEOUT_SECONDS = 10


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


def _is_fully_hash_pinned_export(content: bytes) -> bool:
    """Return whether every emitted uv requirement carries its own hash.

    The fixed exporter invocation does not request index, find-links, binary, or
    global hash directives. Therefore every non-comment logical line must be one
    concrete requirement with at least one ``--hash=`` value. This stricter check
    is intentionally separate from generic requirements-file discovery, where a
    global ``--require-hashes`` directive is still safe to pass to pip's later
    closure preflight.
    """
    lines = _requirement_lines(content)
    return bool(lines) and all("--hash=" in line for line in lines)


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


def _download_trusted_uv_archive() -> bytes:
    """Download the fixed uv release archive through one HTTPS trust boundary."""
    try:
        # Keep the audited URL literal at the network sink so static analysis can
        # prove that neither user data nor repository content selects a scheme,
        # host, path, query, fragment, method, or request header.
        with urllib.request.urlopen(  # nosec B310 -- literal HTTPS URL plus SHA pin
            "https://releases.astral.sh/github/uv/releases/download/0.12.1/"
            "uv-x86_64-unknown-linux-gnu.tar.gz",
            timeout=TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            final_url = urllib.parse.urlparse(response.geturl())
            if (final_url.scheme, final_url.hostname) != (
                "https",
                "releases.astral.sh",
            ):
                raise RuntimeError(
                    "trusted uv archive redirected outside releases.astral.sh"
                )
            payload = response.read(TRUSTED_UV_DOWNLOAD_MAX_BYTES + 1)
    except OSError as exc:
        raise RuntimeError(
            f"trusted uv archive download failed: {type(exc).__name__}"
        ) from exc

    if len(payload) > TRUSTED_UV_DOWNLOAD_MAX_BYTES:
        raise RuntimeError("trusted uv archive exceeded the bounded download size")
    return payload


def _verified_uv_binary(archive_payload: bytes) -> bytes:
    """Return the bounded uv executable after archive and member verification."""
    digest = hashlib.sha256(archive_payload).hexdigest()
    if digest != TRUSTED_UV_ARCHIVE_SHA256:
        raise RuntimeError("trusted uv archive checksum verification failed")

    try:
        with tarfile.open(fileobj=io.BytesIO(archive_payload), mode="r:gz") as bundle:
            try:
                member = bundle.getmember(TRUSTED_UV_ARCHIVE_MEMBER)
            except KeyError as exc:
                raise RuntimeError("trusted uv archive omitted the uv executable") from exc
            if not member.isfile():
                raise RuntimeError("trusted uv archive member is not a regular file")
            if member.size > TRUSTED_UV_BINARY_MAX_BYTES:
                raise RuntimeError("trusted uv executable exceeded the bounded size")
            extracted = bundle.extractfile(member)
            if extracted is None:  # pragma: no cover - guarded by member.isfile()
                raise AssertionError("regular tar members must be extractable")
            binary = extracted.read(TRUSTED_UV_BINARY_MAX_BYTES + 1)
    except tarfile.TarError as exc:
        raise RuntimeError("trusted uv archive could not be parsed") from exc

    if len(binary) != member.size:
        raise RuntimeError("trusted uv executable size did not match its archive metadata")
    return binary


@functools.cache
def _install_trusted_uv() -> str:
    """Install and verify the pinned uv exporter once for this process."""
    tool_dir = pathlib.Path(tempfile.mkdtemp(prefix="opencode-trusted-uv-"))
    tool_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    uv_path = tool_dir / "uv"
    try:
        uv_path.write_bytes(_verified_uv_binary(_download_trusted_uv_archive()))
        uv_path.chmod(0o755)
        try:
            completed = subprocess.run(
                [str(uv_path), "--version"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=TRUSTED_UV_VERSION_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"trusted uv executable verification failed: {type(exc).__name__}"
            ) from exc
        observed = completed.stdout.decode("utf-8", errors="replace").strip()
        if completed.returncode != 0 or observed != f"uv {TRUSTED_UV_VERSION}":
            raise RuntimeError(
                "trusted uv executable reported an unexpected version or exit status"
            )
    except Exception:
        shutil.rmtree(tool_dir, ignore_errors=True)
        raise

    atexit.register(shutil.rmtree, tool_dir, ignore_errors=True)
    return str(uv_path)


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
    """Export one tracked base ``uv.lock`` into a trusted hash-pinned closure.

    The sibling ``pyproject.toml`` determines whether the lock belongs to an
    exportable project. Orphan locks are ignored, and a successful comment-only
    export represents a valid project with no third-party dependency closure.
    Every other exporter failure is fatal: silently dropping a tracked project
    lock would execute coverage without the base dependencies and could turn
    import failures into misleading review feedback.
    """
    project_dir = pathlib.PurePosixPath(lock_path).parent
    pyproject_path = (
        "pyproject.toml"
        if str(project_dir) == "."
        else f"{project_dir}/pyproject.toml"
    )
    lock_content = _git(repo_root, "show", f"{base_sha}:{lock_path}")
    try:
        pyproject_content = _git(repo_root, "show", f"{base_sha}:{pyproject_path}")
    except RuntimeError:
        return None

    uv_path = _install_trusted_uv()

    with tempfile.TemporaryDirectory() as work_dir:
        work_path = pathlib.Path(work_dir)
        (work_path / "uv.lock").write_bytes(lock_content)
        (work_path / "pyproject.toml").write_bytes(pyproject_content)
        try:
            completed = _run_uv_export(work_path, uv_path)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                f"could not run trusted uv export for tracked base lock {lock_path}: "
                f"{type(exc).__name__}"
            ) from exc

    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace")
        normalized_stderr = " ".join(stderr.split())
        detail = (
            normalized_stderr[:500]
            if normalized_stderr
            else f"exit status {completed.returncode}"
        )
        raise RuntimeError(
            f"uv export failed for tracked base lock {lock_path}: {detail}"
        )

    exported = completed.stdout
    if not _requirement_lines(exported):
        return None
    if not _is_fully_hash_pinned_export(exported):
        raise RuntimeError(
            f"uv export for tracked base lock {lock_path} was not fully hash-pinned"
        )
    return exported


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
