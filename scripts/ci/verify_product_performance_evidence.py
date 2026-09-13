#!/usr/bin/env python3
"""Verify sealed product-performance evidence without executing its contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")
_ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PERFORMANCE_PREDICATE_TYPE = (
    "https://contextualwisdomlab.org/attestations/product-performance/v1"
)
_MAX_RESULT_BYTES = 16 * 1024 * 1024
_MAX_RUNTIME_BYTES = 16 * 1024 * 1024
_MAX_FIXTURE_BYTES = 256 * 1024 * 1024


class EvidenceError(ValueError):
    """Describe a deterministic performance-evidence validation failure."""


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate property names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON property: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Any:
    """Reject JSON extensions for NaN and positive or negative infinity."""
    raise EvidenceError(f"non-finite JSON number is forbidden: {value}")


def _require_regular_file(path: Path) -> None:
    """Require an existing regular evidence file without following a symlink."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise EvidenceError(f"missing evidence file: {path.name}") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise EvidenceError(f"evidence member is non-regular: {path.name}")


def _validate_evidence_root(path: Path) -> Path:
    """Return an absolute evidence directory after rejecting unsafe ancestry."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            mode = current.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError) as error:
            raise EvidenceError("evidence root must be an existing directory") from error
        if stat.S_ISLNK(mode):
            raise EvidenceError("evidence root and every ancestor must reject a symlink ancestor")
        if not stat.S_ISDIR(mode):
            raise EvidenceError("evidence root and every ancestor must be directories")
    return absolute


def _validate_filename(value: str, label: str) -> str:
    """Return one safe root-level evidence filename."""
    if not value or value in {".", ".."} or Path(value).name != value:
        raise EvidenceError(f"{label} must be one root-level filename")
    if "/" in value or "\\" in value or "\x00" in value:
        raise EvidenceError(f"{label} contains a forbidden path character")
    return value


def _validate_sha256(value: str, label: str) -> str:
    """Return one canonical lower-case SHA-256 digest."""
    if _SHA256_RE.fullmatch(value) is None:
        raise EvidenceError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _load_json(path: Path, maximum_bytes: int) -> dict[str, Any]:
    """Load strict bounded UTF-8 JSON and require an object root."""
    _require_regular_file(path)
    if path.stat().st_size > maximum_bytes:
        raise EvidenceError(f"JSON file exceeds {maximum_bytes} bytes: {path.name}")
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeError as error:
        raise EvidenceError(f"invalid UTF-8 in {path.name}") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except json.JSONDecodeError as error:
        raise EvidenceError(f"invalid JSON in {path.name}: {error.msg}") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{path.name} must contain a JSON object")
    return value


def _sha256(path: Path) -> str:
    """Hash one regular evidence file without loading it into memory."""
    _require_regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_digest(path: Path, expected: str, label: str) -> None:
    """Require one evidence member to match its external SHA-256 binding."""
    actual = _sha256(path)
    if actual != expected:
        raise EvidenceError(f"{label} digest mismatch: expected {expected}, got {actual}")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Publish deterministic JSON atomically without following an output symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EvidenceError("output manifest path must not be a symlink")
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _validate_controls(arguments: argparse.Namespace) -> None:
    """Validate all caller-supplied control-plane identities before file access."""
    if _REPOSITORY_RE.fullmatch(arguments.source_repository) is None:
        raise EvidenceError("source repository must use owner/name form")
    if _SHA1_RE.fullmatch(arguments.source_sha) is None:
        raise EvidenceError("source SHA must be a lowercase 40-character Git SHA")
    if _POSITIVE_INTEGER_RE.fullmatch(arguments.workflow_run_id) is None:
        raise EvidenceError("workflow run ID must be a positive decimal integer")
    if _POSITIVE_INTEGER_RE.fullmatch(arguments.evidence_artifact_id) is None:
        raise EvidenceError("artifact ID must be a positive decimal integer")
    if _ARTIFACT_NAME_RE.fullmatch(arguments.evidence_artifact_name) is None:
        raise EvidenceError("artifact name must be a bounded GitHub artifact identifier")
    if _ARTIFACT_DIGEST_RE.fullmatch(arguments.evidence_artifact_digest) is None:
        raise EvidenceError("artifact digest must use sha256:<64 lowercase hex>")
    if _PROFILE_RE.fullmatch(arguments.performance_profile) is None:
        raise EvidenceError("performance profile must be a bounded lowercase slug")
    if arguments.predicate_type != _PERFORMANCE_PREDICATE_TYPE:
        raise EvidenceError(
            f"predicate type must be {_PERFORMANCE_PREDICATE_TYPE}"
        )


def _require_selected_profile_binding(
    document: dict[str, Any], label: str, expected_profile: str
) -> None:
    """Bind a caller profile assertion to the sealed result and runtime documents."""
    if document.get("selected_profile") != expected_profile:
        raise EvidenceError(
            f"{label}.selected_profile must equal performance profile {expected_profile}"
        )


def verify(arguments: argparse.Namespace) -> dict[str, Any]:
    """Validate one exact evidence set and publish deterministic trusted receipts."""
    _validate_controls(arguments)
    root = _validate_evidence_root(Path(arguments.evidence_root))
    names = {
        "result": _validate_filename(arguments.result_filename, "result filename"),
        "runtime": _validate_filename(
            arguments.runtime_evidence_filename, "runtime evidence filename"
        ),
        "fixture": _validate_filename(arguments.fixture_filename, "fixture filename"),
    }
    if len(set(names.values())) != len(names):
        raise EvidenceError("result, runtime, and fixture filenames must be distinct")

    actual_members: set[str] = set()
    for member in root.iterdir():
        if member.is_symlink() or not member.is_file():
            raise EvidenceError(f"unexpected non-regular evidence member: {member.name}")
        actual_members.add(member.name)
    expected_members = set(names.values())
    if actual_members != expected_members:
        missing = sorted(expected_members - actual_members)
        extra = sorted(actual_members - expected_members)
        raise EvidenceError(f"evidence cardinality mismatch; missing={missing}, extra={extra}")

    digests = {
        names["result"]: _validate_sha256(arguments.result_sha256, "result SHA-256"),
        names["runtime"]: _validate_sha256(
            arguments.runtime_evidence_sha256, "runtime evidence SHA-256"
        ),
        names["fixture"]: _validate_sha256(arguments.fixture_sha256, "fixture SHA-256"),
    }
    for filename, expected in digests.items():
        _require_digest(root / filename, expected, filename)

    result = _load_json(root / names["result"], _MAX_RESULT_BYTES)
    runtime = _load_json(root / names["runtime"], _MAX_RUNTIME_BYTES)
    _load_json(root / names["fixture"], _MAX_FIXTURE_BYTES)
    if getattr(arguments, "require_selected_profile_binding", False):
        _require_selected_profile_binding(result, "result", arguments.performance_profile)
        _require_selected_profile_binding(runtime, "runtime", arguments.performance_profile)

    predicate = {
        "attestation_claim": "origin_and_integrity_only",
        "does_not_prove": [
            "latency_threshold_passed",
            "production_equivalence",
            "fixture_scientific_validity",
            "fixture_right_clearance",
        ],
        "evidence": {
            "artifact_digest": arguments.evidence_artifact_digest,
            "artifact_id": arguments.evidence_artifact_id,
            "artifact_name": arguments.evidence_artifact_name,
            "fixture": {
                "filename": names["fixture"],
                "sha256": digests[names["fixture"]],
            },
            "result": {
                "filename": names["result"],
                "sha256": digests[names["result"]],
            },
            "runtime": {
                "filename": names["runtime"],
                "sha256": digests[names["runtime"]],
            },
        },
        "performance_profile": arguments.performance_profile,
        "predicate_type": arguments.predicate_type,
        "schema_version": "1.0",
        "source_repository": arguments.source_repository,
        "source_sha": arguments.source_sha,
        "workflow_run_id": arguments.workflow_run_id,
    }
    files = [
        {
            "filename": filename,
            "sha256": digests[filename],
            "size_bytes": (root / filename).stat().st_size,
        }
        for filename in sorted(expected_members)
    ]
    manifest = {
        "evidence_artifact_digest": arguments.evidence_artifact_digest,
        "evidence_artifact_id": arguments.evidence_artifact_id,
        "evidence_artifact_name": arguments.evidence_artifact_name,
        "files": files,
        "performance_profile": arguments.performance_profile,
        "predicate_type": arguments.predicate_type,
        "verification_result": "VALID",
        "source_repository": arguments.source_repository,
        "source_sha": arguments.source_sha,
        "workflow_run_id": arguments.workflow_run_id,
    }
    _atomic_json(Path(arguments.output_predicate), predicate)
    _atomic_json(Path(arguments.output_manifest), manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    """Create the strict CLI parser for sealed performance evidence."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--evidence-artifact-id", required=True)
    parser.add_argument("--evidence-artifact-name", required=True)
    parser.add_argument("--evidence-artifact-digest", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--result-filename", required=True)
    parser.add_argument("--result-sha256", required=True)
    parser.add_argument("--runtime-evidence-filename", required=True)
    parser.add_argument("--runtime-evidence-sha256", required=True)
    parser.add_argument("--fixture-filename", required=True)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--performance-profile", required=True)
    parser.add_argument(
        "--require-selected-profile-binding",
        action="store_true",
        default=argparse.SUPPRESS,
    )
    parser.add_argument("--predicate-type", required=True)
    parser.add_argument("--output-predicate", required=True)
    parser.add_argument("--output-manifest", required=True)
    return parser


def main() -> int:
    """Run CLI verification and return a stable nonzero code for invalid evidence."""
    arguments = _parser().parse_args()
    try:
        verify(arguments)
    except EvidenceError as error:
        print(f"performance evidence rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI dispatch is covered via main()
    raise SystemExit(main())  # pragma: no cover
