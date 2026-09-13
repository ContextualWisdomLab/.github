#!/usr/bin/env python3
"""Materialize one bounded product-performance ZIP as inert regular files."""

from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
import zipfile
import zlib
from pathlib import Path
from typing import BinaryIO

_MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
_MAX_RESULT_BYTES = 16 * 1024 * 1024
_MAX_RUNTIME_BYTES = 16 * 1024 * 1024
_MAX_FIXTURE_BYTES = 256 * 1024 * 1024
_ALLOWED_COMPRESSION = {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}
_COPY_BLOCK_BYTES = 1024 * 1024


class MaterializationError(ValueError):
    """Describe a deterministic sealed-artifact materialization failure."""


def _safe_filename(value: str, label: str) -> str:
    """Return one non-empty root-level filename without path syntax."""
    if not value or value in {".", ".."} or Path(value).name != value:
        raise MaterializationError(f"{label} must be one root-level filename")
    if "/" in value or "\\" in value or "\x00" in value:
        raise MaterializationError(f"{label} must be one root-level filename")
    return value


def _require_regular_archive(path: Path) -> None:
    """Require one bounded regular ZIP input without following a symlink."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise MaterializationError("performance artifact archive is missing") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise MaterializationError("performance artifact archive must be a regular file")
    if path.stat().st_size > _MAX_ARCHIVE_BYTES:
        raise MaterializationError(
            f"performance artifact archive exceeds {_MAX_ARCHIVE_BYTES} bytes"
        )


def _validate_output_parent(output_dir: Path) -> None:
    """Require an existing regular directory parent and a new output path."""
    if output_dir.exists() or output_dir.is_symlink():
        raise MaterializationError("output directory must not already exist")
    parent = output_dir.parent
    try:
        mode = parent.lstat().st_mode
    except FileNotFoundError as error:
        raise MaterializationError("output parent must already exist") from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise MaterializationError("output parent must be a non-symlink directory")


def _validate_member(member: zipfile.ZipInfo, maximum_bytes: int) -> None:
    """Reject unsafe ZIP metadata before one expected member is decompressed."""
    if member.flag_bits & 0x1:
        raise MaterializationError(f"encrypted ZIP member is forbidden: {member.filename}")
    if member.compress_type not in _ALLOWED_COMPRESSION:
        raise MaterializationError(
            f"unsupported ZIP compression for evidence member: {member.filename}"
        )
    mode = (member.external_attr >> 16) & 0xFFFF
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG}:
        raise MaterializationError(f"evidence member must be a regular file: {member.filename}")
    if member.file_size > maximum_bytes:
        raise MaterializationError(
            f"declared size exceeds limit for {member.filename}: {member.file_size}"
        )


def _stream_member(
    source: BinaryIO, destination: Path, maximum_bytes: int, expected_size: int
) -> int:
    """Stream one decompressed member with runtime byte-count enforcement."""
    descriptor = os.open(
        destination,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o400,
    )
    total = 0
    try:
        with os.fdopen(descriptor, "wb") as target:
            while True:
                block = source.read(_COPY_BLOCK_BYTES)
                if not block:
                    break
                total += len(block)
                if total > maximum_bytes:
                    raise MaterializationError(
                        f"decompressed evidence member exceeded {maximum_bytes} bytes"
                    )
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        if total != expected_size:
            raise MaterializationError(
                f"decompressed size mismatch: expected {expected_size}, got {total}"
            )
        os.chmod(destination, 0o400)
        return total
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def materialize(
    archive_path: Path,
    output_dir: Path,
    *,
    result_filename: str,
    runtime_filename: str,
    fixture_filename: str,
) -> dict[str, int]:
    """Validate and stream exactly three bounded evidence members into a new tree."""
    archive = Path(os.path.abspath(archive_path))
    output = Path(os.path.abspath(output_dir))
    _require_regular_archive(archive)
    _validate_output_parent(output)

    names = {
        "result": _safe_filename(result_filename, "result filename"),
        "runtime": _safe_filename(runtime_filename, "runtime evidence filename"),
        "fixture": _safe_filename(fixture_filename, "fixture filename"),
    }
    if len(set(names.values())) != 3:
        raise MaterializationError("result, runtime, and fixture filenames must be distinct")
    limits = {
        names["result"]: _MAX_RESULT_BYTES,
        names["runtime"]: _MAX_RUNTIME_BYTES,
        names["fixture"]: _MAX_FIXTURE_BYTES,
    }

    try:
        bundle = zipfile.ZipFile(archive, "r")
    except (OSError, zipfile.BadZipFile) as error:
        raise MaterializationError("performance artifact must be a valid ZIP archive") from error

    with bundle:
        members = bundle.infolist()
        member_names = [member.filename for member in members]
        if len(member_names) != len(set(member_names)):
            raise MaterializationError("duplicate ZIP evidence member name")
        expected_names = set(names.values())
        actual_names = set(member_names)
        if actual_names != expected_names or len(members) != 3:
            missing = sorted(expected_names - actual_names)
            extra = sorted(actual_names - expected_names)
            raise MaterializationError(
                f"evidence cardinality mismatch; missing={missing}, extra={extra}"
            )

        by_name = {member.filename: member for member in members}
        for filename in sorted(expected_names):
            _validate_member(by_name[filename], limits[filename])

        output.mkdir(mode=0o700)
        total = 0
        try:
            for filename in sorted(expected_names):
                member = by_name[filename]
                with bundle.open(member, "r") as source:
                    total += _stream_member(
                        source,
                        output / filename,
                        maximum_bytes=limits[filename],
                        expected_size=member.file_size,
                    )
            return {"member_count": 3, "total_uncompressed_bytes": total}
        except (zipfile.BadZipFile, zlib.error, EOFError) as error:
            shutil.rmtree(output, ignore_errors=True)
            raise MaterializationError(
                "performance artifact member data is corrupted"
            ) from error
        except Exception:
            shutil.rmtree(output, ignore_errors=True)
            raise


def _parser() -> argparse.ArgumentParser:
    """Create the strict CLI parser for one sealed performance artifact."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--result-filename", required=True)
    parser.add_argument("--runtime-evidence-filename", required=True)
    parser.add_argument("--fixture-filename", required=True)
    return parser


def main() -> int:
    """Run bounded materialization and expose stable invalid-artifact failure."""
    arguments = _parser().parse_args()
    try:
        materialize(
            Path(arguments.archive),
            Path(arguments.output_dir),
            result_filename=arguments.result_filename,
            runtime_filename=arguments.runtime_evidence_filename,
            fixture_filename=arguments.fixture_filename,
        )
    except MaterializationError as error:
        print(f"performance artifact rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch is covered via main()
    raise SystemExit(main())  # pragma: no cover
