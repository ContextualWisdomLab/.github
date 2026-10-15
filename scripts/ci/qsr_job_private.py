#!/usr/bin/env python3
"""Claim, use, and remove one QSR job-private directory and its run witness."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import NotRequired, TypedDict

from scripts.ci.qsr_source_run_paths import (
    SourceRunPathError,
    bind_source_run_paths,
    prepare_source_run_paths,
    relative_paths,
)

WITNESS_NAME = "run-witness.json"
_ACTIONS = ("claim", "use", "cleanup")
_MAX_WITNESS = 4096
_STABLE = ("st_dev", "st_ino", "st_mode", "st_uid", "st_nlink", "st_size")


class JobPrivateError(ValueError):
    """The job-private path or its witness is not bound to this run."""


class PrivateResult(TypedDict):
    """One claim, use, or cleanup record."""

    action: str
    paths: dict[str, Path]
    witness: dict[str, str]
    removed: NotRequired[str]


def witness_document(
    job: str, source: str, run_id: str, run_attempt: str
) -> dict[str, str]:
    """Build the witness for one run, its head, and the hash of that binding."""
    relative_paths(job, source, run_id, run_attempt)
    body = {
        "head": source,
        "job": job,
        "run_attempt": run_attempt,
        "run_id": run_id,
    }
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {**body, "sha256": hashlib.sha256(encoded).hexdigest()}


def _contained(workspace: Path, path: Path) -> None:
    """Refuse a private root that escapes the workspace through a link or file."""
    root = Path(workspace)
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise JobPrivateError("private path escapes the workspace") from exc
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise JobPrivateError("private path escapes the workspace")
        if current != path and current.exists() and not current.is_dir():
            raise JobPrivateError("private path escapes the workspace")


def bound_private_paths(
    workspace: Path,
    *,
    job: str,
    source: str,
    run_id: str,
    run_attempt: str,
    evidence_roots: tuple[Path, ...] = (),
    tool_roots: tuple[Path, ...] = (),
) -> dict[str, Path]:
    """Return the path-contract directories after checking this private root."""
    paths = bind_source_run_paths(
        workspace,
        job=job,
        source=source,
        run_id=run_id,
        run_attempt=run_attempt,
        evidence_roots=evidence_roots,
        tool_roots=tool_roots,
    )
    _contained(workspace, paths["cleanup"])
    return paths


def _publish(path: Path, payload: dict[str, str]) -> None:
    """Create a new witness file without replacing an existing node."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    try:
        descriptor = os.open(
            path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError as exc:
        raise JobPrivateError("witness already exists") from exc
    except OSError as exc:
        raise JobPrivateError("witness is not a new file") from exc
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(encoded)


def claim_job_private(
    workspace: Path,
    *,
    job: str,
    source: str,
    run_id: str,
    run_attempt: str,
    evidence_roots: tuple[Path, ...] = (),
    tool_roots: tuple[Path, ...] = (),
) -> PrivateResult:
    """Create this run's private root and witness, refusing a path that exists."""
    paths = bound_private_paths(
        workspace,
        job=job,
        source=source,
        run_id=run_id,
        run_attempt=run_attempt,
        evidence_roots=evidence_roots,
        tool_roots=tool_roots,
    )
    document = witness_document(job, source, run_id, run_attempt)
    prepare_source_run_paths(paths)
    _publish(paths["cleanup"] / WITNESS_NAME, document)
    return {"action": "claim", "paths": paths, "witness": document}


def _mode_ok(path: Path) -> None:
    """Require a real private directory owned by this job's mode."""
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise JobPrivateError("private path is missing") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise JobPrivateError("private path is missing")
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise JobPrivateError("private path is not private")


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject a witness object that repeats a field."""
    found: dict[str, object] = {}
    for key, value in pairs:
        if key in found:
            raise JobPrivateError("witness is not the current binding")
        found[key] = value
    return found


def _read_witness(path: Path) -> dict[str, object]:
    """Read one regular witness file without following a link."""
    if path.is_symlink():
        raise JobPrivateError("witness is not a regular file")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise JobPrivateError("witness is not a regular file") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise JobPrivateError("witness is not a regular file")
        if info.st_nlink != 1:
            raise JobPrivateError("witness is not a regular file")
        if info.st_size <= 0:
            raise JobPrivateError("witness is not a regular file")
        if info.st_size > _MAX_WITNESS:
            raise JobPrivateError("witness too large")
        data = os.read(descriptor, _MAX_WITNESS + 1)
        after = os.fstat(descriptor)
        if len(data) != info.st_size:
            raise JobPrivateError("witness changed while reading")
        if any(getattr(after, key) != getattr(info, key) for key in _STABLE):
            raise JobPrivateError("witness changed while reading")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise JobPrivateError("witness is not the current binding") from exc
    return payload


def _matches(payload: dict[str, object], expected: dict[str, str]) -> dict[str, str]:
    """Accept only the witness for this run, head, and binding hash."""
    if type(payload) is not dict:
        raise JobPrivateError("witness is not the current binding")
    if set(payload) != set(expected):
        raise JobPrivateError("witness is not the current binding")
    for key, value in expected.items():
        observed = payload[key]
        if type(observed) is not str:
            raise JobPrivateError("witness is not the current binding")
        if observed != value:
            raise JobPrivateError("witness is not the current binding")
    return expected


def use_job_private(
    workspace: Path,
    *,
    job: str,
    source: str,
    run_id: str,
    run_attempt: str,
    evidence_roots: tuple[Path, ...] = (),
    tool_roots: tuple[Path, ...] = (),
) -> PrivateResult:
    """Use the private path only when its witness matches this run."""
    paths = bound_private_paths(
        workspace,
        job=job,
        source=source,
        run_id=run_id,
        run_attempt=run_attempt,
        evidence_roots=evidence_roots,
        tool_roots=tool_roots,
    )
    _mode_ok(paths["cleanup"])
    _mode_ok(paths["output"])
    payload = _read_witness(paths["cleanup"] / WITNESS_NAME)
    document = witness_document(job, source, run_id, run_attempt)
    _matches(payload, document)
    return {"action": "use", "paths": paths, "witness": document}


def _refuse_special(root: Path) -> None:
    """Refuse cleanup when the private tree contains a non-file node."""
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        for name in filenames:
            info = (current / name).lstat()
            if stat.S_ISLNK(info.st_mode) or stat.S_ISREG(info.st_mode):
                continue
            raise JobPrivateError("private path contains an unsupported node")


def _remove_tree(root: Path) -> None:
    """Unlink the private tree without following a directory link."""
    for dirpath, dirnames, filenames in os.walk(root, topdown=False, followlinks=False):
        current = Path(dirpath)
        for name in filenames:
            os.unlink(current / name)
        for name in dirnames:
            child = current / name
            if child.is_symlink():
                os.unlink(child)
            else:
                os.rmdir(child)
    os.rmdir(root)


def cleanup_job_private(
    workspace: Path,
    *,
    job: str,
    source: str,
    run_id: str,
    run_attempt: str,
    evidence_roots: tuple[Path, ...] = (),
    tool_roots: tuple[Path, ...] = (),
) -> PrivateResult:
    """Remove only the private root whose witness matches this run."""
    current = use_job_private(
        workspace,
        job=job,
        source=source,
        run_id=run_id,
        run_attempt=run_attempt,
        evidence_roots=evidence_roots,
        tool_roots=tool_roots,
    )
    root = current["paths"]["cleanup"]
    _refuse_special(root)
    removed = str(root)
    _remove_tree(root)
    return {
        "action": "cleanup",
        "paths": current["paths"],
        "witness": current["witness"],
        "removed": removed,
    }


def _receipt(result: PrivateResult) -> dict[str, str]:
    """Return the execution record for one claim, use, or cleanup."""
    paths = result["paths"]
    witness = result["witness"]
    body = {
        "action": str(result["action"]),
        "checkout": str(paths["checkout"]),
        "cleanup": str(paths["cleanup"]),
        "cwd": str(paths["cwd"]),
        "head": str(witness["head"]),
        "job": str(witness["job"]),
        "output": str(paths["output"]),
        "run_attempt": str(witness["run_attempt"]),
        "run_id": str(witness["run_id"]),
        "sha256": str(witness["sha256"]),
    }
    if result["action"] == "cleanup":
        body["removed"] = str(result["removed"])
    return body


def main(argv: list[str] | None = None) -> int:
    """Run one private-path action and print its witness record."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=_ACTIONS)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--evidence", type=Path, action="append", default=[])
    parser.add_argument("--tool", type=Path, action="append", default=[])
    args = parser.parse_args(argv)
    dispatch = {
        "claim": claim_job_private,
        "use": use_job_private,
        "cleanup": cleanup_job_private,
    }
    try:
        result = dispatch[args.action](
            args.workspace,
            job=args.job,
            source=args.source,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            evidence_roots=tuple(args.evidence),
            tool_roots=tuple(args.tool),
        )
    except JobPrivateError as exc:
        print(f"SRC03-PRIVATE-001: {exc}", file=sys.stderr)
        return 1
    except SourceRunPathError as exc:
        print(f"SRC03-PATH-001: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(_receipt(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
