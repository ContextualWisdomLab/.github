#!/usr/bin/env python3
"""Bound and validate one scientific-validation receipt pair for signer handoff."""

from __future__ import annotations

import argparse
import importlib.util
import os
import stat
import sys
from pathlib import Path
from types import ModuleType
from typing import Sequence

_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_VERIFIER_FILENAME = "verify_scientific_validation_evidence.py"


def _load_verifier_module() -> ModuleType:
    """Load the sibling semantic verifier from the same immutable owner checkout."""
    source = Path(__file__).with_name(_VERIFIER_FILENAME)
    spec = importlib.util.spec_from_file_location("cwl_scientific_validation_verifier", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("scientific-validation semantic verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verifier = _load_verifier_module()
EvidenceError = verifier.EvidenceError


def _read_bounded_regular_file(path: Path, label: str) -> tuple[bytes, tuple[int, int]]:
    """Read one signer receipt inode once and return bytes plus descriptor identity."""
    absolute = Path(os.path.abspath(path))
    _, parent_descriptor = verifier._open_directory_without_symlinks(absolute.parent)
    descriptor: int | None = None
    try:
        try:
            descriptor = os.open(
                absolute.name,
                os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                dir_fd=parent_descriptor,
            )
        except OSError as error:
            raise EvidenceError(f"{label} must be an existing regular file") from error
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise EvidenceError(f"{label} must be an existing regular file")
        identity = (metadata.st_dev, metadata.st_ino)
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(_MAX_RECEIPT_BYTES + 1)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent_descriptor)
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise EvidenceError(f"{label} exceeds {_MAX_RECEIPT_BYTES} bytes")
    return raw, identity


def validate_receipt_files(manifest_path: Path, predicate_path: Path) -> dict[str, object]:
    """Validate exact bounded receipt bytes from two distinct regular-file inodes."""
    manifest = Path(os.path.abspath(manifest_path))
    predicate = Path(os.path.abspath(predicate_path))
    if manifest == predicate:
        raise EvidenceError("receipt manifest and predicate must use distinct paths")
    manifest_bytes, manifest_identity = _read_bounded_regular_file(manifest, "receipt manifest")
    predicate_bytes, predicate_identity = _read_bounded_regular_file(
        predicate, "scientific-validation predicate"
    )
    if manifest_identity == predicate_identity:
        raise EvidenceError("receipt manifest and predicate must use distinct regular-file inodes")
    return verifier.validate_receipt_manifest(manifest_bytes, predicate_bytes)


def _parser() -> argparse.ArgumentParser:
    """Create the strict signer-handoff receipt reader CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-manifest", required=True)
    parser.add_argument("--predicate", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Return a stable nonzero result for invalid signer-handoff receipt files."""
    arguments = _parser().parse_args(argv)
    try:
        validate_receipt_files(Path(arguments.receipt_manifest), Path(arguments.predicate))
    except EvidenceError as error:
        print(f"scientific validation receipt rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
