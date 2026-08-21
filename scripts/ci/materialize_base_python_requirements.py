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
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by Python 3.10 CI.
    import tomli as tomllib


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
UV_EXACT_REQUIREMENT_RE = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
    r"(?:\[[A-Za-z0-9._-]+(?:,[A-Za-z0-9._-]+)*\])?"
    r"==[^\s;]+(?:\s*;\s*\S(?:.*\S)?)?"
)
UV_SHA256_HASH_RE = re.compile(r"--hash=sha256:[0-9a-fA-F]{64}")
UV_EXPORT_TIMEOUT_SECONDS = 120
TRUSTED_UV_VERSION = "0.12.1"
TRUSTED_UV_TARGET_TRIPLE = "x86_64-unknown-linux-gnu"
TRUSTED_UV_VERSION_OUTPUT = f"uv {TRUSTED_UV_VERSION} ({TRUSTED_UV_TARGET_TRIPLE})"
TRUSTED_UV_ARCHIVE_URL = (
    "https://github.com/astral-sh/uv/releases/download/0.12.1/"
    "uv-x86_64-unknown-linux-gnu.tar.gz"
)
TRUSTED_UV_RELEASE_HOST = "github.com"
TRUSTED_UV_ASSET_HOSTS = frozenset(
    {
        "release-assets.githubusercontent.com",
        "objects.githubusercontent.com",
    }
)
TRUSTED_UV_FINAL_HOSTS = frozenset({TRUSTED_UV_RELEASE_HOST, *TRUSTED_UV_ASSET_HOSTS})
TRUSTED_UV_ARCHIVE_SHA256 = (
    "90b2f223fb69d19db49e117da601f64978593417988530aa733d456141b4bcbb"
)
TRUSTED_UV_ARCHIVE_MEMBER = "uv-x86_64-unknown-linux-gnu/uv"
TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS = 120
TRUSTED_UV_DOWNLOAD_MAX_BYTES = 64 * 1024 * 1024
TRUSTED_UV_BINARY_MAX_BYTES = 64 * 1024 * 1024
TRUSTED_UV_VERSION_TIMEOUT_SECONDS = 10
TRUSTED_UV_ORIGIN_ERROR = (
    "trusted uv archive redirected outside the fixed GitHub release HTTPS origin"
)


def _https_default_port(parsed: urllib.parse.ParseResult) -> bool:
    """Return whether one parsed URL uses the implicit or explicit HTTPS port."""
    try:
        return parsed.port in (None, 443)
    except ValueError:
        return False


def _is_trusted_uv_https_host(
    url: str,
    allowed_hosts: frozenset[str],
) -> bool:
    """Return whether ``url`` is HTTPS, default-port, and host-allowlisted."""
    parsed = urllib.parse.urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and parsed.username is None
        and parsed.password is None
        and _https_default_port(parsed)
    )


def _is_trusted_uv_release_request(url: str) -> bool:
    """Return whether the current request is still the GitHub Releases origin."""
    return _is_trusted_uv_https_host(url, frozenset({TRUSTED_UV_RELEASE_HOST}))


def _is_trusted_uv_asset_location(url: str) -> bool:
    """Return whether the next hop is an official GitHub release-asset host."""
    return _is_trusted_uv_https_host(url, TRUSTED_UV_ASSET_HOSTS)


def _is_trusted_uv_final_origin(url: str) -> bool:
    """Return whether the completed response stayed on a trusted HTTPS origin."""
    return _is_trusted_uv_https_host(url, TRUSTED_UV_FINAL_HOSTS)


class _TrustedUvReleaseAssetRedirects(urllib.request.HTTPRedirectHandler):
    """Follow one GitHub Releases hop onto the official asset CDN only."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        response: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request:
        """Allow github.com → GitHub asset CDN and reject every other hop."""
        if not _is_trusted_uv_release_request(request.full_url) or not (
            _is_trusted_uv_asset_location(new_url)
        ):
            raise RuntimeError(TRUSTED_UV_ORIGIN_ERROR)
        followed = super().redirect_request(
            request,
            response,
            code,
            message,
            headers,
            new_url,
        )
        if followed is None:
            raise RuntimeError(TRUSTED_UV_ORIGIN_ERROR)
        return followed


@functools.cache
def _install_trusted_uv_url_opener() -> None:
    """Install one process-wide no-proxy opener for the fixed GitHub URL."""
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _TrustedUvReleaseAssetRedirects(),
    )
    urllib.request.install_opener(opener)


def _is_candidate_lock_name(name: str) -> bool:
    """Return whether a file name is a possible pip requirements lock."""
    return name == "requirements.lock" or (
        fnmatch.fnmatch(name, "requirements*.txt")
        and not fnmatch.fnmatch(name, "requirements-*-ci-hashes.txt")
    )


def _is_candidate_lock_path(path: pathlib.PurePosixPath) -> bool:
    """Return whether one safe tracked path can name a pip requirements lock.

    In addition to conventional ``requirements*.txt`` names, repositories often
    keep concrete environment closures as direct children such as
    ``requirements/ci.txt`` or ``service/requirements/package.txt``. Only direct
    ``.txt`` children of a directory named ``requirements`` gain this path-based
    eligibility; content must still pass the independent complete hash-pin
    validation before it reaches the trusted image build context.
    """
    return _is_candidate_lock_name(path.name) or (
        path.suffix == ".txt" and path.parent.name == "requirements"
    )


def _bounded_requirement_include_target(
    line: str,
) -> pathlib.PurePosixPath | None:
    """Return the safe relative target of one bounded requirements include.

    The target may use any normalized relative ``.txt`` name, including names
    such as ``other-hashes.txt``. Eligibility does not confer trust: the exact
    base-tree target must later be a regular blob containing only exact
    SHA-256-pinned package requirements.
    """
    fields = line.split()
    if len(fields) != 2 or fields[0] not in {"-r", "--requirement"}:
        return None
    target = fields[1]
    if (
        target.startswith(("-", "~"))
        or "\\" in target
        or ":" in target
        or "?" in target
        or "#" in target
    ):
        return None
    include_path = pathlib.PurePosixPath(target)
    if (
        not include_path.parts
        or target != include_path.as_posix()
        or include_path.is_absolute()
        or "." in include_path.parts
        or ".." in include_path.parts
        or include_path.suffix != ".txt"
    ):
        return None
    return include_path


def _is_bounded_requirement_include(line: str) -> bool:
    """Return whether one include has a safe relative ``.txt`` target."""
    return _bounded_requirement_include_target(line) is not None


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
    """Return whether content carries only trusted pins or bounded includes.

    Discovery is content-based rather than name-based so exact hash-pinned locks
    in service subdirectories and role-specific requirements files can be
    considered for offline coverage. Candidate syntax is deliberately stricter
    than a substring search: each package line must be an exact ``==`` pin with
    one or more complete SHA-256 hashes, or a bounded relative requirements
    include. A global ``--require-hashes`` directive is not trust evidence by
    itself. The downstream installer separately preflights every candidate as an
    independent ``pip --require-hashes`` closure, so syntax eligibility never
    substitutes for dependency-closure proof.
    """
    lines = _requirement_lines(content)
    requirement_lines = [line for line in lines if line != "--require-hashes"]
    if not requirement_lines:
        return False
    return all(
        _is_fully_hash_pinned_requirement(line)
        or _is_bounded_requirement_include(line)
        for line in requirement_lines
    )


def _is_flat_materializable_lock(content: bytes) -> bool:
    """Return whether content is one standalone exact SHA-256 requirements lock.

    Selected sources are renamed to generated flat files. Relative ``-r`` and
    ``--requirement`` edges therefore lose the source directory that gives them
    meaning. Only independent exact package pins cross this publication boundary
    until a complete immutable include graph can be reconstructed and rewritten.
    """
    lines = _requirement_lines(content)
    requirement_lines = [line for line in lines if line != "--require-hashes"]
    return bool(requirement_lines) and all(
        _is_fully_hash_pinned_requirement(line) for line in requirement_lines
    )
def _is_fully_hash_pinned_requirement(line: str) -> bool:
    """Return whether one uv-export line is an exact package pin with SHA-256 hashes."""
    fields = re.split(r"\s+(?=--hash=)", line)
    if len(fields) < 2:
        return False
    requirement, *hashes = fields
    if UV_EXACT_REQUIREMENT_RE.fullmatch(requirement) is None:
        return False
    return all(UV_SHA256_HASH_RE.fullmatch(hash_value) for hash_value in hashes)


def _is_fully_hash_pinned_export(content: bytes) -> bool:
    """Return whether every emitted uv requirement is exactly SHA-256 pinned.

    The fixed exporter invocation does not request index, find-links, binary, or
    global hash directives. Every non-comment logical line must therefore be one
    normalized package ``==`` pin with at least one complete SHA-256 hash. Option
    lines, local/direct references, other algorithms, and truncated hashes are
    rejected even when they contain a ``--hash=`` substring.
    """
    lines = _requirement_lines(content)
    return bool(lines) and all(_is_fully_hash_pinned_requirement(line) for line in lines)


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
    _install_trusted_uv_url_opener()
    try:
        # Keep the audited URL literal at the network sink so static analysis can
        # prove that neither user data nor repository content selects a scheme,
        # host, path, query, fragment, method, or request header.
        with urllib.request.urlopen(  # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected  # nosec B310
            "https://github.com/astral-sh/uv/releases/download/0.12.1/"
            "uv-x86_64-unknown-linux-gnu.tar.gz",
            timeout=TRUSTED_UV_DOWNLOAD_TIMEOUT_SECONDS,
        ) as response:
            if not _is_trusted_uv_final_origin(response.geturl()):
                raise RuntimeError(TRUSTED_UV_ORIGIN_ERROR)
            payload = bytearray()
            while len(payload) <= TRUSTED_UV_DOWNLOAD_MAX_BYTES:
                chunk = response.read(
                    TRUSTED_UV_DOWNLOAD_MAX_BYTES + 1 - len(payload)
                )
                if not chunk:
                    break
                payload.extend(chunk)
    except OSError as exc:
        raise RuntimeError(
            f"trusted uv archive download failed: {type(exc).__name__}"
        ) from exc

    if len(payload) > TRUSTED_UV_DOWNLOAD_MAX_BYTES:
        raise RuntimeError("trusted uv archive exceeded the bounded download size")
    return bytes(payload)


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
    if sys.platform != "linux" or platform.machine() != "x86_64":
        raise RuntimeError(
            "the pinned trusted uv archive supports only linux x86_64 runners"
        )
    tool_dir = pathlib.Path(tempfile.mkdtemp(prefix="opencode-trusted-uv-"))
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
        if completed.returncode != 0 or observed != TRUSTED_UV_VERSION_OUTPUT:
            raise RuntimeError(
                "trusted uv executable reported an unexpected version or exit status"
            )
    except Exception:
        shutil.rmtree(tool_dir, ignore_errors=True)
        raise

    atexit.register(shutil.rmtree, tool_dir, ignore_errors=True)
    return str(uv_path)


def _trusted_uv_export_environment(work_dir: pathlib.Path) -> dict[str, str]:
    """Create the minimal deterministic environment allowed to influence uv export."""
    directories = {
        "HOME": work_dir / ".uv-home",
        "TMPDIR": work_dir / ".uv-tmp",
        "XDG_CACHE_HOME": work_dir / ".uv-cache",
        "XDG_CONFIG_HOME": work_dir / ".uv-config",
    }
    for directory in directories.values():
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return {
        "HOME": str(directories["HOME"]),
        "NO_COLOR": "1",
        "PATH": os.defpath,
        "TMPDIR": str(directories["TMPDIR"]),
        "UV_NO_ENV_FILE": "1",
        "UV_PYTHON_DOWNLOADS": "never",
        "XDG_CACHE_HOME": str(directories["XDG_CACHE_HOME"]),
        "XDG_CONFIG_HOME": str(directories["XDG_CONFIG_HOME"]),
    }


def _run_uv_export(
    work_dir: pathlib.Path,
    uv_path: str,
    *,
    timeout: float = UV_EXPORT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``uv export`` for a reconstructed base project and return the result.

    ``--frozen`` forbids lock mutation and ``--offline`` forbids network access.
    A minimal environment and ephemeral cache/config/home directories prevent
    runner-level configuration, dotenv files, Python downloads, or persistent
    cache state from selecting export behavior. Project metadata discovery stays
    enabled so the reconstructed ``pyproject.toml`` remains authoritative.
    """
    return subprocess.run(
        [
            uv_path,
            "export",
            "--frozen",
            "--offline",
            "--no-cache",
            "--no-progress",
            "--color",
            "never",
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
        env=_trusted_uv_export_environment(work_dir),
    )


def _uv_pyproject_path(lock_path: str) -> str:
    """Return the sibling project metadata path for one safe tracked uv lock."""
    project_dir = pathlib.PurePosixPath(lock_path).parent
    return (
        "pyproject.toml"
        if str(project_dir) == "."
        else f"{project_dir}/pyproject.toml"
    )


def _reject_unsupported_uv_workspace(
    pyproject_content: bytes,
    pyproject_path: str,
) -> None:
    """Reject uv workspace metadata until every immutable member is reconstructed."""
    try:
        metadata = tomllib.loads(pyproject_content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(
            f"could not parse tracked base pyproject metadata {pyproject_path}"
        ) from exc

    try:
        workspace = metadata["tool"]["uv"]["workspace"]
    except (KeyError, TypeError):
        return

    raise RuntimeError(
        f"tracked base uv workspace in {pyproject_path} {workspace!r} is not "
        "supported by isolated lock materialization"
    )


def _export_uv_lock(
    repo_root: pathlib.Path, base_sha: str, lock_path: str
) -> bytes | None:
    """Export one tracked base ``uv.lock`` into a trusted hash-pinned closure.

    The caller proves that the sibling ``pyproject.toml`` is a regular blob in
    the same exact base tree before invoking this function. Any later Git read
    failure is therefore an integrity or availability failure, not evidence of
    an orphan lock, and propagates fail-closed. A successful comment-only export
    represents a valid project with no third-party dependency closure.
    """
    pyproject_path = _uv_pyproject_path(lock_path)
    lock_content = _git(repo_root, "show", f"{base_sha}:{lock_path}")
    pyproject_content = _git(repo_root, "show", f"{base_sha}:{pyproject_path}")
    _reject_unsupported_uv_workspace(pyproject_content, pyproject_path)
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


def _regular_base_blob_paths(entries: bytes) -> list[tuple[str, pathlib.PurePosixPath]]:
    """Parse exact-tree output into safe regular blob paths in repository order."""
    regular_blobs: list[tuple[str, pathlib.PurePosixPath]] = []
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
        regular_blobs.append((path, candidate))
    return regular_blobs


def base_hash_locks(repo_root: pathlib.Path, base_sha: str) -> list[tuple[str, bytes]]:
    """Return regular hash-lock blobs from the exact validated base commit."""
    if not SHA_RE.fullmatch(base_sha):
        raise ValueError("base SHA must be exactly 40 hexadecimal characters")

    entries = _git(repo_root, "ls-tree", "-r", "-z", "--full-tree", base_sha)
    regular_blobs = _regular_base_blob_paths(entries)
    regular_paths = {path for path, _candidate in regular_blobs}
    locks: list[tuple[str, bytes]] = []
    for path, candidate in regular_blobs:
        if _is_candidate_lock_path(candidate):
            content = _git(repo_root, "show", f"{base_sha}:{path}")
            if _is_hash_pinned(content):
                locks.append((path, content))
        elif candidate.name == "uv.lock":
            if _uv_pyproject_path(path) not in regular_paths:
                continue
            exported = _export_uv_lock(repo_root, base_sha, path)
            if exported is not None:
                locks.append((path, exported))
    return sorted(locks, key=lambda item: item[0])


def _included_base_lock_blobs(
    repo_root: pathlib.Path,
    base_sha: str,
    source_path: str,
    content: bytes,
    regular_paths: set[str],
) -> list[tuple[pathlib.PurePosixPath, bytes]]:
    """Load direct bounded includes from the exact base as complete closures."""
    source_parent = pathlib.PurePosixPath(source_path).parent
    included: dict[pathlib.PurePosixPath, bytes] = {}
    for line in _requirement_lines(content):
        target = _bounded_requirement_include_target(line)
        if target is None:
            continue
        resolved = source_parent / target
        resolved_path = resolved.as_posix()
        if resolved_path not in regular_paths:
            raise RuntimeError(
                f"bounded include {target} from {source_path} is not a regular base blob"
            )
        included_content = _git(repo_root, "show", f"{base_sha}:{resolved_path}")
        if not _is_flat_materializable_lock(included_content):
            raise RuntimeError(
                f"bounded include {resolved_path} must contain only exact SHA-256 pins"
            )
        included[target] = included_content
    return sorted(included.items(), key=lambda item: item[0].as_posix())


def _rewrite_materialized_includes(
    content: bytes, include_directory: str, source_path: str = ""
) -> bytes:
    """Rewrite root include targets to their preserved generated subtree."""
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise RuntimeError(f"base lock {source_path} is not valid UTF-8") from exc
    rewritten: list[str] = []
    for raw_line in text.splitlines(keepends=True):
        body = raw_line.rstrip("\r\n")
        ending = raw_line[len(body) :]
        stripped = body.strip()
        target = _bounded_requirement_include_target(stripped)
        if target is None:
            rewritten.append(raw_line)
            continue
        indentation = body[: len(body) - len(body.lstrip())]
        option = stripped.split()[0]
        rewritten.append(
            f"{indentation}{option} {include_directory}/{target.as_posix()}{ending}"
        )
    return "".join(rewritten).encode("utf-8")


def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
) -> list[dict[str, str]]:
    """Write base locks and resolvable bounded includes into a safe context."""
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_repo = repo_root.resolve()
    entries = _git(resolved_repo, "ls-tree", "-r", "-z", "--full-tree", base_sha)
    regular_paths = {
        path for path, _candidate in _regular_base_blob_paths(entries)
    }
    manifest: list[dict[str, str]] = []
    for index, (source_path, content) in enumerate(
        base_hash_locks(resolved_repo, base_sha)
    ):
        generated_name = f"requirements-{index:03d}.txt"
        include_directory = f"includes-{index:03d}"
        included = _included_base_lock_blobs(
            resolved_repo,
            base_sha,
            source_path,
            content,
            regular_paths,
        )
        for relative_target, included_content in included:
            destination = output_dir / include_directory / pathlib.Path(*relative_target.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(included_content)
        destination = output_dir / generated_name
        destination.write_bytes(
            _rewrite_materialized_includes(content, include_directory, source_path)
        )
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
