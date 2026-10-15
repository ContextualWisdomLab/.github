#!/usr/bin/env python3
"""Admit one QSR output artifact only when it is bound to one source."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path
from typing import NoReturn

from scripts.ci.qsr_source_run_paths import (
    SourceRunPathError,
    bind_source_run_paths,
)

_STALE = "SRC03-ART-STALE"
_SYMLINK = "SRC03-ART-SYMLINK"
_EMPTY = "SRC03-ART-EMPTY"
_BOUND = "SRC03-ART-BOUND"
_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK


class SourceArtifactError(ValueError):
    """An output artifact is not a regular file bound to this source."""

    def __init__(self, code: str, message: str, record: dict[str, object]) -> None:
        """Store the refusal code and the source-bound execution record."""
        self.code = code
        self.record = record
        super().__init__(message)


def _record(code: str, source: str, fixture: Path, bound: bool) -> dict[str, object]:
    """Build the execution record pairing one fixture path with one source."""
    return {
        "bound": bound,
        "code": code,
        "fixture": str(fixture),
        "result": "accepted" if bound else "refused",
        "source": source,
    }


def _refuse(code: str, message: str, source: str, fixture: Path) -> NoReturn:
    """Record the fixture against this source and refuse it."""
    raise SourceArtifactError(code, message, _record(code, source, fixture, False))


def _read_binding(binding: Path) -> bytes | None:
    """Read a small regular sidecar without following a symlink."""
    try:
        descriptor = os.open(binding, _READ_FLAGS)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size == 0
            or info.st_size > 128
            or info.st_nlink != 1
        ):
            return None
        return os.read(descriptor, info.st_size)
    finally:
        os.close(descriptor)


def _unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Reject a sidecar object that repeats a field."""
    found: dict[str, object] = {}
    for key, value in pairs:
        if key in found:
            raise ValueError("duplicate sidecar field")
        found[key] = value
    return found


def _binding_matches(binding: Path, source: str) -> bool:
    """Return whether the sidecar is exactly this source identity."""
    payload = _read_binding(binding)
    if payload is None:
        return False
    try:
        parsed = json.loads(payload.decode("utf-8"), object_pairs_hook=_unique_fields)
    except (UnicodeDecodeError, ValueError):
        return False
    return parsed == {"source": source}


def admit_source_artifact(
    workspace: Path,
    artifact: Path,
    *,
    job: str,
    source: str,
    run_id: str,
    run_attempt: str,
) -> dict[str, object]:
    """Admit one regular artifact bound to this source, or refuse it."""
    paths = bind_source_run_paths(
        workspace,
        job=job,
        source=source,
        run_id=run_id,
        run_attempt=run_attempt,
    )
    output = paths["output"]
    artifact = Path(artifact)
    if output.is_symlink() or not output.is_dir():
        _refuse(_STALE, "artifact is not bound to this source", source, artifact)
    if not artifact.is_absolute() or artifact.parent.is_symlink():
        _refuse(_STALE, "artifact is not bound to this source", source, artifact)
    if artifact.parent.resolve() != output.resolve():
        _refuse(_STALE, "artifact is not bound to this source", source, artifact)
    try:
        info = os.lstat(artifact)
    except OSError:
        _refuse(_STALE, "artifact is not bound to this source", source, artifact)
    if stat.S_ISLNK(info.st_mode):
        _refuse(_SYMLINK, "artifact is a symlink", source, artifact)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        _refuse(_STALE, "artifact is not bound to this source", source, artifact)
    if info.st_size == 0:
        _refuse(_EMPTY, "artifact is empty", source, artifact)
    binding = artifact.with_name(artifact.name + ".source.json")
    if not _binding_matches(binding, source):
        _refuse(_STALE, "artifact is not bound to this source", source, artifact)
    return _record(_BOUND, source, artifact, True)


def main(argv: list[str] | None = None) -> int:
    """Print one source-bound artifact decision and return 0 only when admitted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--record", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = admit_source_artifact(
            args.workspace,
            args.artifact,
            job=args.job,
            source=args.source,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
        )
        status = 0
    except SourceArtifactError as exc:
        payload = exc.record
        print(f"{exc.code}: {exc}", file=sys.stderr)
        status = 1
    except SourceRunPathError as exc:
        print(f"SRC03-PATH-001: {exc}", file=sys.stderr)
        return 1
    line = json.dumps(payload, sort_keys=True)
    print(line)
    if args.record is not None:
        with args.record.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
