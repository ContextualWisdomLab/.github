#!/usr/bin/env python3
"""Materialize an offline Cargo vendor directory from a validated base commit.

The sandboxed coverage-measurement container runs with ``--network=none`` (see
``opencode-review-dispatch.yml``'s "Measure test and docstring evidence" step). Python and
JavaScript dependencies already have an offline path through
``materialize_base_python_requirements.py`` and ``materialize_base_javascript_packages.py``, which
run here -- on the runner, before the network-isolated container exists -- and bake a base-pinned
dependency closure into the trusted image. Rust/Cargo had no equivalent: every coverage run against
a Rust crate (directly via ``cargo llvm-cov``, or indirectly through a PyO3/maturin extension a
Python test suite imports) needed ``index.crates.io``, which the offline container can never reach.
Confirmed live across ``fast-mlsirm`` PRs #1868-#1892 (dispatch runs 34884397167 and siblings):
``cargo llvm-cov`` failed with ``Could not resolve host: index.crates.io``, and the generic Python
pytest path failed at collection with ``ImportError: cannot import name '_core'`` because nothing in
the sandbox ever builds the compiled extension. Both surfaced as a generic "Coverage gate: failure",
indistinguishable from a real regression in the pull request.

This mirrors the Python materializer's trust model: only the validated base commit's Cargo
manifests are read (never the pull request's), and vendoring itself uses Cargo's own built-in
per-package checksum verification (every ``[[package]]`` entry in a lock file carries a
``checksum``), so no separate hash-pin parser is needed the way ``requirements*.txt`` needed one.

An explicit ``--head-sha`` opts into a narrower lock-repair intake: every Cargo manifest
remains byte-identical to base, every registry record (including resolved dependency edges)
must already occur in the base lock union, and local identities must already be base-pinned.
Only lock bytes are overlaid; Cargo vendor --locked still verifies the unchanged manifests
and package checksums. Separate provenance records the base manifests and head lock blobs.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import subprocess
import sys
import tempfile

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by Python 3.10 CI.
    import tomli as tomllib


SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
CARGO_VENDOR_TIMEOUT_SECONDS = 600


def _git(repo_root: pathlib.Path, *args: str) -> bytes:
    """Run one read-only git command against the materialized repository."""
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


def _regular_cargo_blob_paths(repo_root: pathlib.Path, base_sha: str) -> list[str]:
    """Return tracked, non-symlink ``Cargo.toml``/``Cargo.lock`` paths at ``base_sha``."""
    entries = _git(repo_root, "ls-tree", "-r", "-z", "--full-tree", base_sha)
    paths: list[str] = []
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
        if candidate.name in ("Cargo.toml", "Cargo.lock"):
            paths.append(path)
    return sorted(paths)


def _is_workspace_manifest(content: bytes) -> bool:
    """Return whether one ``Cargo.toml`` blob declares a ``[workspace]`` table."""
    try:
        parsed = tomllib.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError("could not parse a tracked base Cargo.toml") from exc
    return "workspace" in parsed


def _select_vendor_roots(
    repo_root: pathlib.Path, base_sha: str, cargo_paths: list[str]
) -> list[str]:
    """Return every directory whose base lock must be vendored, primary root first.

    A base tree may legitimately hold several lock roots: the standard cargo-fuzz
    layout declares ``[workspace]`` in both the repository root and ``fuzz/`` so the
    fuzz crate opts out of the parent workspace, and the two locks resolve *different*
    crate sets. Selecting one root and dropping the rest would silently vendor an
    incomplete closure, so every root is vendored into one shared directory via
    ``cargo vendor --sync`` and every lock is asserted with ``--locked``.

    What still fails closed is a root that cannot be reconciled at all: a manifest
    declaring a workspace with no sibling ``Cargo.lock``, or a lock with no sibling
    ``Cargo.toml``. Those are unresolvable rather than merely plural.
    """
    manifests = {
        (path.rsplit("/", 1)[0] if "/" in path else ".")
        for path in cargo_paths
        if path.endswith("Cargo.toml")
    }
    locks = {
        (path.rsplit("/", 1)[0] if "/" in path else ".")
        for path in cargo_paths
        if path.endswith("Cargo.lock")
    }
    for manifest_path in sorted(
        path for path in cargo_paths if path.endswith("Cargo.toml")
    ):
        content = _git(repo_root, "show", f"{base_sha}:{manifest_path}")
        if not _is_workspace_manifest(content):
            continue
        manifest_dir = manifest_path.rsplit("/", 1)[0] if "/" in manifest_path else "."
        if manifest_dir not in locks:
            raise RuntimeError(
                f"base Cargo workspace root {manifest_dir} has no sibling Cargo.lock"
            )
    for lock_dir in sorted(locks):
        if lock_dir not in manifests:
            raise RuntimeError(
                f"base Cargo.lock at {lock_dir} has no sibling Cargo.toml"
            )
    if not locks:
        return []
    # Deterministic order with the repository root first when it is one of the roots,
    # so the primary --manifest-path is stable across runs and hosts.
    ordered = sorted(locks, key=lambda root: (root != ".", root))
    return ordered


def _placeholder_target_paths(manifest_content: bytes) -> list[str]:
    """Return package target source paths a manifest needs present to parse.

    ``cargo vendor`` never compiles anything -- it only resolves and downloads the locked
    dependency graph -- but Cargo still refuses to *parse* a package manifest whose declared
    targets do not exist on disk. Real source is never required for vendoring, so this returns
    the conventional and any explicitly declared target paths; the caller writes empty
    placeholder files at each one.
    """
    try:
        parsed = tomllib.loads(manifest_content.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    if "package" not in parsed:
        return []
    paths = {"src/lib.rs", "src/main.rs"}
    lib_path = (
        parsed.get("lib", {}).get("path")
        if isinstance(parsed.get("lib"), dict)
        else None
    )
    if isinstance(lib_path, str):
        paths.add(lib_path)
    for bin_target in (
        parsed.get("bin", []) if isinstance(parsed.get("bin"), list) else []
    ):
        bin_path = bin_target.get("path") if isinstance(bin_target, dict) else None
        if isinstance(bin_path, str):
            paths.add(bin_path)
    return sorted(paths)


def _reconstruct_base_tree(
    repo_root: pathlib.Path,
    base_sha: str,
    cargo_paths: list[str],
    work_dir: pathlib.Path,
) -> None:
    """Write every tracked base Cargo manifest into ``work_dir`` at its repository path.

    Each package manifest's conventional/declared target paths also get an empty placeholder
    file -- see :func:`_placeholder_target_paths` for why real source is never needed here.
    """
    for path in cargo_paths:
        content = _git(repo_root, "show", f"{base_sha}:{path}")
        destination = work_dir / pathlib.Path(*pathlib.PurePosixPath(path).parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        if destination.name == "Cargo.toml":
            for target_path in _placeholder_target_paths(content):
                target_relative_path = pathlib.PurePosixPath(target_path)
                if (
                    target_relative_path.is_absolute()
                    or ".." in target_relative_path.parts
                ):
                    raise RuntimeError(
                        "Cargo target path must stay inside its manifest root: "
                        f"{target_path}"
                    )
                target_destination = destination.parent / pathlib.Path(
                    *target_relative_path.parts
                )
                target_destination.parent.mkdir(parents=True, exist_ok=True)
                if not target_destination.exists():
                    target_destination.write_bytes(b"")


def _run_cargo_vendor(
    manifest_path: pathlib.Path,
    vendor_dir: pathlib.Path,
    sync_manifests: list[pathlib.Path] | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Vendor the union of the base manifests, asserting every lock stays unchanged.

    ``--sync`` adds each further root's manifest to the same vendor directory, so no
    root's dependencies are dropped. ``--locked`` makes cargo refuse to re-resolve:
    without it a lock that disagrees with its manifest would be quietly updated and
    the vendored set would no longer be the committed closure.
    """
    command = [
        "cargo",
        "vendor",
        "--locked",
        "--manifest-path",
        str(manifest_path),
        "--versioned-dirs",
    ]
    for sync_manifest in sync_manifests or []:
        command.extend(["--sync", str(sync_manifest)])
    command.append(str(vendor_dir))
    return subprocess.run(
        command,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=CARGO_VENDOR_TIMEOUT_SECONDS,
    )


def _normalized_lock_records(content: bytes) -> list[dict]:
    """Compare bounded lock records with uniquely resolved dependency identities."""
    parsed = tomllib.loads(content.decode("utf-8"))
    packages = parsed.get("package")
    if (
        set(parsed) - {"version", "package"}
        or parsed.get("version") not in {3, 4}
        or not isinstance(packages, list)
        or len(packages) > 10000
    ):
        raise ValueError("head intake requires a bounded version 3/4 Cargo lock")
    identities = {}
    by_name = {}
    for package in packages:
        if not isinstance(package, dict):
            raise ValueError("invalid Cargo lock package")
        source = package.get("source")
        allowed = {"name", "version", "dependencies"}
        if source is not None:
            allowed |= {"source", "checksum"}
            if (
                source != "registry+https://github.com/rust-lang/crates.io-index"
                or not isinstance(package.get("checksum"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", package["checksum"])
            ):
                raise ValueError(
                    "head intake requires existing crates.io checksum pins"
                )
        if set(package) - allowed or any(
            not isinstance(package.get(k), str) or not package[k]
            for k in ("name", "version")
        ):
            raise ValueError("unsupported Cargo lock package fields")
        identity = (package["name"], package["version"], source)
        if identity in identities:
            raise ValueError("duplicate Cargo lock package identity")
        identities[identity] = package
        by_name.setdefault(identity[0], []).append(identity)
    records = []
    for package in packages:
        dependencies = package.get("dependencies", [])
        if not isinstance(dependencies, list) or len(dependencies) > 10000:
            raise ValueError("invalid Cargo lock dependencies")
        edges = []
        for dependency in dependencies:
            if not isinstance(dependency, str):
                raise ValueError("invalid Cargo lock dependency identity")
            parts = dependency.split()
            if not 1 <= len(parts) <= 3:
                raise ValueError("unsupported Cargo lock dependency identity")
            candidates = [
                identity
                for identity in by_name.get(parts[0], [])
                if (len(parts) < 2 or identity[1] == parts[1])
                and (len(parts) < 3 or f"({identity[2]})" == parts[2])
            ]
            if len(candidates) != 1:
                raise ValueError("missing or ambiguous Cargo lock dependency identity")
            edges.append(candidates[0])
        if len(edges) != len(set(edges)):
            raise ValueError("duplicate Cargo lock dependency edge")
        records.append({**package, "dependencies": sorted(edges, key=repr)})
    return records


def _validated_head_locks(
    repo_root: pathlib.Path, base_sha: str, head_sha: str, cargo_paths: list[str]
) -> tuple[dict[str, bytes], dict]:
    """Allow head locks only to recombine records pinned in the base lock union.

    Manifest bytes remain from base. Local-package closure still requires the
    unchanged base manifests to pass Cargo vendor --locked; this function does
    not authorize new registry records, git sources or package checksums.
    """
    if not SHA_RE.fullmatch(head_sha):
        raise ValueError("head SHA must be exactly 40 hexadecimal characters")
    head_paths = _regular_cargo_blob_paths(repo_root, head_sha)
    if head_paths != cargo_paths:
        raise ValueError("head Cargo manifest/lock paths must equal base")
    changed = _git(repo_root, "diff", "--name-only", "-z", base_sha, head_sha).split(
        b"\0"
    )
    if any(
        path and pathlib.PurePosixPath(path.decode()).name == "Cargo.toml"
        for path in changed
    ):
        raise ValueError("head Cargo manifests must remain byte-identical to base")

    def lock_bytes(revision: str, path: str) -> bytes:
        """Read a revision-pinned lock after checking its bounded blob size."""
        size = int(_git(repo_root, "cat-file", "-s", f"{revision}:{path}"))
        if size > 16 * 1024 * 1024:
            raise ValueError("Cargo lock exceeds bounded size")
        return _git(repo_root, "show", f"{revision}:{path}")

    paths = [path for path in cargo_paths if path.endswith("Cargo.lock")]
    base_records = []
    for path in paths:
        base_records.extend(_normalized_lock_records(lock_bytes(base_sha, path)))
    registry_records = {
        json.dumps(row, sort_keys=True) for row in base_records if row.get("source")
    }
    local_identities = {
        (row["name"], row["version"]) for row in base_records if not row.get("source")
    }
    locks = {}
    receipts = []
    for path in paths:
        content = lock_bytes(head_sha, path)
        for row in _normalized_lock_records(content):
            if row.get("source"):
                if json.dumps(row, sort_keys=True) not in registry_records:
                    raise ValueError(
                        "head registry record differs from base lock union"
                    )
            elif (row["name"], row["version"]) not in local_identities:
                raise ValueError("head local identity differs from base lock union")
        locks[path] = content
        receipts.append(
            {
                "path": path,
                "base_lock_blob": _git(repo_root, "rev-parse", f"{base_sha}:{path}")
                .decode()
                .strip(),
                "lock_blob": _git(repo_root, "rev-parse", f"{head_sha}:{path}")
                .decode()
                .strip(),
            }
        )
    return locks, {
        "manifest_revision": base_sha.lower(),
        "lock_revision": head_sha.lower(),
        "locks": receipts,
    }


def materialize(
    repo_root: pathlib.Path,
    base_sha: str,
    output_dir: pathlib.Path,
    *,
    vendor_dir_for_config: str | None = None,
    head_sha: str | None = None,
) -> list[str]:
    """Vendor base manifests with base locks or explicitly bounded head locks.

    Returns the list of source-tree-relative ``Cargo.lock`` paths that were vendored. An empty
    list means no Rust project (or no lock file) exists at the base commit, which is not an
    error -- most repositories reviewed by this pipeline have no Rust code at all.

    ``vendor_dir_for_config`` overrides the ``directory = `` path written into
    ``cargo-config.toml``. Vendoring runs on the runner (this materializer's own working
    directory), but the vendored files are later copied into the trusted coverage image at a
    fixed path; the emitted config must name that final in-image path, not the runner's
    temporary one.
    """
    if not SHA_RE.fullmatch(base_sha):
        raise ValueError("base SHA must be exactly 40 hexadecimal characters")
    if output_dir.exists() and output_dir.is_symlink():
        raise ValueError("output directory must not be a symlink")
    output_dir.mkdir(parents=True, exist_ok=True)

    resolved_repo = repo_root.resolve()
    cargo_paths = _regular_cargo_blob_paths(resolved_repo, base_sha)
    vendor_roots = _select_vendor_roots(resolved_repo, base_sha, cargo_paths)
    manifest: list[str] = []
    head_locks, provenance = (
        _validated_head_locks(resolved_repo, base_sha, head_sha, cargo_paths)
        if head_sha is not None
        else ({}, None)
    )
    if vendor_roots:
        primary_root, *additional_roots = vendor_roots

        def _manifest_for(root: str, base: pathlib.Path) -> pathlib.Path:
            """Locate a vendor root manifest within the reconstructed base tree."""
            return base / ("Cargo.toml" if root == "." else f"{root}/Cargo.toml")

        def _lock_for(root: str) -> str:
            """Return the repository-relative lock path for a vendor root."""
            return "Cargo.lock" if root == "." else f"{root}/Cargo.lock"

        with tempfile.TemporaryDirectory() as work_dir:
            work_path = pathlib.Path(work_dir)
            _reconstruct_base_tree(resolved_repo, base_sha, cargo_paths, work_path)
            for path, content in head_locks.items():
                (work_path / path).write_bytes(content)
            manifest_path = _manifest_for(primary_root, work_path)
            sync_manifests = [
                _manifest_for(root, work_path) for root in additional_roots
            ]
            # Every root's lock is reported, so a failure names the whole vendored set
            # rather than only the primary root.
            lock_path = ", ".join(_lock_for(root) for root in vendor_roots)
            vendor_dir = output_dir / "vendor"
            try:
                completed = _run_cargo_vendor(manifest_path, vendor_dir, sync_manifests)
            except (OSError, subprocess.TimeoutExpired) as exc:
                raise RuntimeError(
                    f"could not run trusted cargo vendor for base manifest {lock_path}: "
                    f"{type(exc).__name__}"
                ) from exc
            if completed.returncode != 0:
                stderr = completed.stderr.decode("utf-8", errors="replace")
                normalized_stderr = " ".join(stderr.split())
                detail = (
                    normalized_stderr[:500]
                    if normalized_stderr
                    else (f"exit status {completed.returncode}")
                )
                raise RuntimeError(
                    f"cargo vendor failed for base lock {lock_path}: {detail}"
                )
            config_text = completed.stdout
            if vendor_dir_for_config is not None:
                config_text = config_text.replace(
                    str(vendor_dir).encode("utf-8"),
                    vendor_dir_for_config.encode("utf-8"),
                )
            (output_dir / "cargo-config.toml").write_bytes(config_text)
        manifest = [_lock_for(root) for root in vendor_roots]

    if provenance is not None:
        (output_dir / "lock-provenance.json").write_text(
            json.dumps(provenance, indent=2) + "\n"
        )
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    """Materialize the base Cargo vendor directory and report what was selected."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--base-sha", required=True)
    parser.add_argument("--head-sha", default=None)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--vendor-dir-for-config", default=None)
    args = parser.parse_args(argv)

    try:
        manifest = materialize(
            args.repo_root,
            args.base_sha,
            args.output_dir,
            vendor_dir_for_config=args.vendor_dir_for_config,
            head_sha=args.head_sha,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(
            f"::error::Could not materialize base Rust dependencies: {exc}",
            file=sys.stderr,
        )
        return 1

    if manifest:
        if args.head_sha:
            print(
                f"Materialized Cargo vendor directory from base manifests and bounded head locks: {manifest[0]}."
            )
        else:
            print(
                f"Materialized trusted base Cargo vendor directory from {manifest[0]}."
            )
    else:
        print(
            "No tracked Cargo.lock exists at the validated base SHA; Rust vendoring skipped."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
