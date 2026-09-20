#!/usr/bin/env python3
"""Verify sealed scientific-validation evidence without executing its contents.

This module validates represented evidence identity only.  It deliberately does
not authenticate the caller, workflow, artifact producer, or signature.  Those
are separate organization-control-plane responsibilities owned by the reusable
attestation workflow tracked in #2299.
"""

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
from typing import Any, Iterable, Sequence

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PREDICATE_TYPE = "https://contextualwisdomlab.org/attestations/scientific-validation/v1"
_SCHEMA_VERSION = "1.0"
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_REQUIRED_DOCUMENT_KEYS = frozenset(
    {
        "schema_version",
        "source_repository",
        "source_sha",
        "workflow_run_id",
        "profile_sha256",
        "profile_chronology_sha256",
        "exact_head_receipt_sha256",
        "exact_head_artifact_sha256",
        "exact_head_status",
        "seed_manifest_sha256",
        "recovery_evidence_sha256",
        "replication_provenance_sha256",
        "execution_artifact_sha256",
    }
)


class EvidenceError(ValueError):
    """Represent one deterministic scientific-evidence intake rejection."""


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Build a JSON object while rejecting duplicate property names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON property: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Any:
    """Reject the non-standard JSON NaN and infinity constants."""
    raise EvidenceError(f"non-finite JSON number is forbidden: {value}")


def _require_repository(value: str) -> str:
    """Return an owner/name repository identifier or fail closed."""
    if _REPOSITORY_RE.fullmatch(value) is None:
        raise EvidenceError("source repository must use owner/name form")
    return value


def _require_git_sha(value: str) -> str:
    """Return a canonical full Git SHA-1 identifier or fail closed."""
    if _SHA1_RE.fullmatch(value) is None:
        raise EvidenceError("source SHA must be a lowercase 40-character Git SHA")
    return value


def _require_positive_integer(value: str, label: str) -> str:
    """Return one positive decimal identifier without accepting signs or zero."""
    if _POSITIVE_INTEGER_RE.fullmatch(value) is None:
        raise EvidenceError(f"{label} must be a positive decimal integer")
    return value


def _require_sha256(value: str, label: str) -> str:
    """Return one canonical lowercase SHA-256 digest."""
    if _SHA256_RE.fullmatch(value) is None:
        raise EvidenceError(f"{label} must be 64 lowercase hexadecimal characters")
    return value


def _require_artifact_name(value: str) -> str:
    """Return a bounded GitHub artifact name."""
    if _ARTIFACT_NAME_RE.fullmatch(value) is None:
        raise EvidenceError("artifact name must be a bounded GitHub artifact identifier")
    return value


def _require_artifact_digest(value: str) -> str:
    """Return a GitHub artifact SHA-256 digest descriptor."""
    if _ARTIFACT_DIGEST_RE.fullmatch(value) is None:
        raise EvidenceError("artifact digest must use sha256:<64 lowercase hex>")
    return value


def _require_predicate_type(value: str) -> str:
    """Reject predicate substitution instead of accepting caller-selected schemas."""
    if value != _PREDICATE_TYPE:
        raise EvidenceError(f"predicate type must be {_PREDICATE_TYPE}")
    return value


def _require_filename(value: str) -> str:
    """Return one root-level filename that cannot escape the sealed directory."""
    if not value or value in {".", ".."} or Path(value).name != value:
        raise EvidenceError("evidence filename must be one root-level filename")
    if "/" in value or "\\" in value or "\x00" in value:
        raise EvidenceError("evidence filename contains a forbidden path character")
    return value


def _validate_root(path: Path) -> Path:
    """Resolve no symlinks while requiring every existing path component to be a directory."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            mode = current.lstat().st_mode
        except (FileNotFoundError, NotADirectoryError) as error:
            raise EvidenceError("evidence root must be an existing directory") from error
        if stat.S_ISLNK(mode):
            raise EvidenceError("evidence root and every ancestor must reject symlinks")
        if not stat.S_ISDIR(mode):
            raise EvidenceError("evidence root and every ancestor must be directories")
    return absolute


def _require_regular_file(path: Path) -> None:
    """Require an existing regular file without following a symlink."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise EvidenceError(f"missing evidence file: {path.name}") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise EvidenceError(f"evidence member is non-regular: {path.name}")


def _sha256(path: Path) -> str:
    """Hash one regular evidence file as a bounded-memory stream."""
    _require_regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _load_document(path: Path) -> dict[str, Any]:
    """Load one bounded strict UTF-8 JSON object."""
    _require_regular_file(path)
    if path.stat().st_size > _MAX_EVIDENCE_BYTES:
        raise EvidenceError(f"evidence JSON exceeds {_MAX_EVIDENCE_BYTES} bytes")
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
    except UnicodeError as error:
        raise EvidenceError("evidence JSON must be strict UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except json.JSONDecodeError as error:
        raise EvidenceError(f"invalid evidence JSON: {error.msg}") from error
    if not isinstance(value, dict):
        raise EvidenceError("evidence JSON root must be an object")
    actual_keys = frozenset(value)
    if actual_keys != _REQUIRED_DOCUMENT_KEYS:
        missing = sorted(_REQUIRED_DOCUMENT_KEYS - actual_keys)
        extra = sorted(actual_keys - _REQUIRED_DOCUMENT_KEYS)
        raise EvidenceError(f"evidence schema mismatch; missing={missing}, extra={extra}")
    return value


def _require_string(document: dict[str, Any], key: str) -> str:
    """Return a required JSON string without coercion."""
    value = document[key]
    if not isinstance(value, str):
        raise EvidenceError(f"{key} must be a JSON string")
    return value


def _require_document_binding(document: dict[str, Any], key: str, expected: str) -> None:
    """Require one represented identity to equal the independently supplied control value."""
    actual = _require_string(document, key)
    if actual != expected:
        raise EvidenceError(f"{key} does not match the authenticated control value")


def _validate_execution_artifacts(
    document: dict[str, Any], expected: Sequence[str]
) -> list[str]:
    """Validate ordered per-replication execution artifact identity without set collapse."""
    value = document["execution_artifact_sha256"]
    if not isinstance(value, list):
        raise EvidenceError("execution_artifact_sha256 must be a JSON array")
    if len(value) < 2:
        raise EvidenceError("execution_artifact_sha256 must contain at least two replications")
    execution = [
        _require_sha256(item, "execution artifact SHA-256")
        if isinstance(item, str)
        else _raise_execution_type()
        for item in value
    ]
    if len(set(execution)) != len(execution):
        raise EvidenceError("execution artifact SHA-256 identities must be distinct")
    if execution != list(expected):
        raise EvidenceError("execution_artifact_sha256 does not match ordered control evidence")
    return execution


def _raise_execution_type() -> str:
    """Fail closed when a replication artifact identity is not represented as text."""
    raise EvidenceError("execution artifact SHA-256 must be a JSON string")


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Publish canonical JSON atomically without replacing through an output symlink."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise EvidenceError("output path must not be a symlink")
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


def verify(arguments: argparse.Namespace) -> dict[str, Any]:
    """Verify one sealed evidence document and emit deterministic unsigned intake receipts."""
    source_repository = _require_repository(arguments.source_repository)
    source_sha = _require_git_sha(arguments.source_sha)
    workflow_run_id = _require_positive_integer(arguments.workflow_run_id, "workflow run ID")
    artifact_id = _require_positive_integer(arguments.evidence_artifact_id, "artifact ID")
    artifact_name = _require_artifact_name(arguments.evidence_artifact_name)
    artifact_digest = _require_artifact_digest(arguments.evidence_artifact_digest)
    predicate_type = _require_predicate_type(arguments.predicate_type)
    evidence_filename = _require_filename(arguments.evidence_filename)
    evidence_sha256 = _require_sha256(arguments.evidence_sha256, "evidence SHA-256")

    expected = {
        "profile_sha256": _require_sha256(arguments.profile_sha256, "profile SHA-256"),
        "profile_chronology_sha256": _require_sha256(
            arguments.profile_chronology_sha256, "profile chronology SHA-256"
        ),
        "exact_head_receipt_sha256": _require_sha256(
            arguments.exact_head_receipt_sha256, "exact-head receipt SHA-256"
        ),
        "exact_head_artifact_sha256": _require_sha256(
            arguments.exact_head_artifact_sha256, "exact-head artifact SHA-256"
        ),
        "seed_manifest_sha256": _require_sha256(
            arguments.seed_manifest_sha256, "seed manifest SHA-256"
        ),
        "recovery_evidence_sha256": _require_sha256(
            arguments.recovery_evidence_sha256, "recovery evidence SHA-256"
        ),
        "replication_provenance_sha256": _require_sha256(
            arguments.replication_provenance_sha256, "replication provenance SHA-256"
        ),
    }
    expected_execution = [
        _require_sha256(value, "execution artifact SHA-256")
        for value in arguments.execution_artifact_sha256
    ]
    if len(expected_execution) < 2 or len(set(expected_execution)) != len(expected_execution):
        raise EvidenceError("ordered control execution artifact identities must be at least two and distinct")

    root = _validate_root(Path(arguments.evidence_root))
    members = list(root.iterdir())
    if len(members) != 1 or members[0].name != evidence_filename:
        raise EvidenceError("sealed scientific evidence cardinality must be exactly one named member")
    evidence_path = members[0]
    _require_regular_file(evidence_path)
    actual_evidence_sha256 = _sha256(evidence_path)
    if actual_evidence_sha256 != evidence_sha256:
        raise EvidenceError(
            f"evidence SHA-256 mismatch: expected {evidence_sha256}, got {actual_evidence_sha256}"
        )

    document = _load_document(evidence_path)
    if document["schema_version"] != _SCHEMA_VERSION:
        raise EvidenceError(f"schema_version must be {_SCHEMA_VERSION}")
    _require_document_binding(document, "source_repository", source_repository)
    _require_document_binding(document, "source_sha", source_sha)
    document_run_id = document["workflow_run_id"]
    if not isinstance(document_run_id, int) or isinstance(document_run_id, bool):
        raise EvidenceError("workflow_run_id must be a JSON integer")
    if str(document_run_id) != workflow_run_id:
        raise EvidenceError("workflow_run_id does not match the authenticated control value")
    for key, expected_value in expected.items():
        _require_document_binding(document, key, expected_value)
    if _require_string(document, "exact_head_status") != "passed":
        raise EvidenceError("exact_head_status must be passed before attestation")
    execution_artifacts = _validate_execution_artifacts(document, expected_execution)

    predicate = {
        "attestation_claim": "origin_and_integrity_only",
        "does_not_prove": [
            "psychometric_numerical_acceptance",
            "rmse_or_bias_threshold_passed",
            "construct_validity",
            "estimator_validity",
            "production_equivalence",
        ],
        "evidence": {
            "artifact_digest": artifact_digest,
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "evidence_filename": evidence_filename,
            "evidence_sha256": evidence_sha256,
            "exact_head_artifact_sha256": expected["exact_head_artifact_sha256"],
            "exact_head_receipt_sha256": expected["exact_head_receipt_sha256"],
            "execution_artifact_sha256": execution_artifacts,
            "profile_chronology_sha256": expected["profile_chronology_sha256"],
            "profile_sha256": expected["profile_sha256"],
            "recovery_evidence_sha256": expected["recovery_evidence_sha256"],
            "replication_provenance_sha256": expected["replication_provenance_sha256"],
            "seed_manifest_sha256": expected["seed_manifest_sha256"],
        },
        "predicate_type": predicate_type,
        "schema_version": _SCHEMA_VERSION,
        "source_repository": source_repository,
        "source_sha": source_sha,
        "workflow_run_id": workflow_run_id,
    }
    manifest = {
        "evidence_artifact_digest": artifact_digest,
        "evidence_artifact_id": artifact_id,
        "evidence_artifact_name": artifact_name,
        "evidence_filename": evidence_filename,
        "evidence_sha256": evidence_sha256,
        "execution_artifact_sha256": execution_artifacts,
        "predicate_type": predicate_type,
        "source_repository": source_repository,
        "source_sha": source_sha,
        "verification_result": "VALID",
        "workflow_run_id": workflow_run_id,
    }
    _atomic_json(Path(arguments.output_predicate), predicate)
    _atomic_json(Path(arguments.output_manifest), manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    """Create the strict command-line parser for scientific evidence intake."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--evidence-artifact-id", required=True)
    parser.add_argument("--evidence-artifact-name", required=True)
    parser.add_argument("--evidence-artifact-digest", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--evidence-filename", required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--profile-chronology-sha256", required=True)
    parser.add_argument("--exact-head-receipt-sha256", required=True)
    parser.add_argument("--exact-head-artifact-sha256", required=True)
    parser.add_argument("--seed-manifest-sha256", required=True)
    parser.add_argument("--recovery-evidence-sha256", required=True)
    parser.add_argument("--replication-provenance-sha256", required=True)
    parser.add_argument("--execution-artifact-sha256", action="append", required=True)
    parser.add_argument("--predicate-type", required=True)
    parser.add_argument("--output-predicate", required=True)
    parser.add_argument("--output-manifest", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run intake verification and return a stable nonzero result for invalid evidence."""
    arguments = _parser().parse_args(argv)
    try:
        verify(arguments)
    except EvidenceError as error:
        print(f"scientific validation evidence rejected: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
