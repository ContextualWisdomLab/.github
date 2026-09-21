#!/usr/bin/env python3
"""Verify sealed scientific-validation evidence without executing its contents.

This module validates represented evidence identity only. It deliberately does
not authenticate the caller, workflow, artifact producer, or signature. Those
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
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any, Iterable, Sequence

_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_POSITIVE_INTEGER_RE = re.compile(r"^[1-9][0-9]*$")
_ARTIFACT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
_ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PREDICATE_TYPE = "https://contextualwisdomlab.org/attestations/scientific-validation/v1"
_MANIFEST_TYPE = (
    "https://contextualwisdomlab.org/attestations/scientific-validation-manifest/v1"
)
_SCHEMA_VERSION = "1.0"
_MANIFEST_SCHEMA_VERSION = "1.0"
_MAX_EVIDENCE_BYTES = 16 * 1024 * 1024
_DOES_NOT_PROVE = [
    "psychometric_numerical_acceptance",
    "rmse_or_bias_threshold_passed",
    "construct_validity",
    "estimator_validity",
    "production_equivalence",
]
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
_REQUIRED_PREDICATE_KEYS = frozenset(
    {
        "attestation_claim",
        "does_not_prove",
        "evidence",
        "predicate_type",
        "schema_version",
        "source_repository",
        "source_sha",
        "workflow_run_id",
    }
)
_REQUIRED_PREDICATE_EVIDENCE_KEYS = frozenset(
    {
        "artifact_digest",
        "artifact_id",
        "artifact_name",
        "artifact_size_in_bytes",
        "evidence_filename",
        "evidence_sha256",
        "exact_head_artifact_sha256",
        "exact_head_receipt_sha256",
        "exact_head_status",
        "execution_artifact_sha256",
        "profile_chronology_sha256",
        "profile_sha256",
        "recovery_evidence_sha256",
        "replication_provenance_sha256",
        "seed_manifest_sha256",
    }
)
_REQUIRED_MANIFEST_KEYS = frozenset(
    {
        "manifest_type",
        "schema_version",
        "evidence_artifact_digest",
        "evidence_artifact_id",
        "evidence_artifact_name",
        "evidence_artifact_size_in_bytes",
        "evidence_filename",
        "evidence_sha256",
        "execution_artifact_sha256",
        "predicate_sha256",
        "predicate_type",
        "source_repository",
        "source_sha",
        "verification_result",
        "workflow_run_id",
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


def _open_directory_without_symlinks(path: Path) -> tuple[Path, int]:
    """Pin one directory inode by walking every path component without following symlinks."""
    absolute = Path(os.path.abspath(path))
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(absolute.anchor, flags)
    try:
        for component in absolute.parts[1:]:
            next_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_descriptor
    except OSError as error:
        os.close(descriptor)
        raise EvidenceError(
            "evidence root and every ancestor must be existing unsymlinked directories"
        ) from error
    return absolute, descriptor


def _validate_output_path(path: Path, sealed_root: Path) -> tuple[Path, int]:
    """Pin an output parent directory while keeping publication outside sealed evidence."""
    absolute = Path(os.path.abspath(path))
    if absolute == sealed_root or sealed_root in absolute.parents:
        raise EvidenceError("verifier outputs must remain outside the sealed evidence root")
    try:
        _, descriptor = _open_directory_without_symlinks(absolute.parent)
    except EvidenceError as error:
        raise EvidenceError(
            f"output parent must not traverse a symlink or non-directory: {error}"
        ) from error
    return absolute, descriptor


def _require_output_leaf_absent(parent_descriptor: int, filename: str) -> None:
    """Refuse every pre-existing output leaf before verifier-owned publication."""
    try:
        mode = os.stat(filename, dir_fd=parent_descriptor, follow_symlinks=False).st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise EvidenceError("output path must not be a symbolic link")
    raise EvidenceError("output leaf must not already exist")


def _require_regular_file(path: Path) -> None:
    """Require an existing regular file without following a symlink."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise EvidenceError(f"missing evidence file: {path.name}") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise EvidenceError(f"evidence member is non-regular: {path.name}")


def _read_evidence_once(path: Path | str, *, dir_fd: int | None = None) -> bytes:
    """Read one bounded regular evidence inode once without blocking or following the leaf symlink."""
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
            dir_fd=dir_fd,
        )
    except OSError as error:
        raise EvidenceError(f"evidence member is non-regular: {Path(path).name}") from error
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise EvidenceError(f"evidence member is non-regular: {Path(path).name}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            raw = stream.read(_MAX_EVIDENCE_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(raw) > _MAX_EVIDENCE_BYTES:
        raise EvidenceError(f"evidence JSON exceeds {_MAX_EVIDENCE_BYTES} bytes")
    return raw


def _load_strict_json_object(raw: bytes, label: str) -> dict[str, Any]:
    """Parse strict UTF-8 JSON bytes and require an object root."""
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise EvidenceError(f"{label} must be strict UTF-8") from error
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except EvidenceError:
        raise
    except json.JSONDecodeError as error:
        raise EvidenceError(f"invalid {label}: {error.msg}") from error
    except (RecursionError, ValueError) as error:
        raise EvidenceError(f"invalid {label}: JSON parser resource limit exceeded") from error
    if not isinstance(value, dict):
        raise EvidenceError(f"{label} root must be an object")
    return value


def _require_exact_keys(
    document: dict[str, Any], required: frozenset[str], label: str
) -> None:
    """Reject missing or unknown properties at one closed-schema boundary."""
    actual_keys = frozenset(document)
    if actual_keys != required:
        missing = sorted(required - actual_keys)
        extra = sorted(actual_keys - required)
        raise EvidenceError(f"{label} schema mismatch; missing={missing}, extra={extra}")


def _load_document(raw: bytes) -> dict[str, Any]:
    """Parse one bounded strict evidence object and enforce its closed schema."""
    value = _load_strict_json_object(raw, "evidence JSON")
    _require_exact_keys(value, _REQUIRED_DOCUMENT_KEYS, "evidence")
    return value


def _require_string(document: dict[str, Any], key: str) -> str:
    """Return a required JSON string without coercion."""
    value = document[key]
    if not isinstance(value, str):
        raise EvidenceError(f"{key} must be a JSON string")
    return value


def _require_literal(document: dict[str, Any], key: str, expected: str) -> str:
    """Require one string field to equal its owner-defined literal contract."""
    value = _require_string(document, key)
    if value != expected:
        raise EvidenceError(f"{key} must be {expected}")
    return value


def _require_document_binding(document: dict[str, Any], key: str, expected: str) -> None:
    """Require one represented identity to equal the independently supplied control value."""
    actual = _require_string(document, key)
    if actual != expected:
        raise EvidenceError(f"{key} does not match the authenticated control value")


def _require_manifest_predicate_binding(label: str, manifest_value: Any, predicate_value: Any) -> None:
    """Reject contradictory duplicate claims across one manifest/predicate receipt pair."""
    if manifest_value != predicate_value:
        raise EvidenceError(f"{label} in receipt manifest does not match predicate")


def _raise_execution_type() -> str:
    """Fail closed when a replication artifact identity is not represented as text."""
    raise EvidenceError("execution artifact SHA-256 must be a JSON string")


def _validate_execution_artifact_list(value: Any) -> list[str]:
    """Validate one ordered, non-collapsed list of execution artifact identities."""
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
    return execution


def _validate_execution_artifacts(
    document: dict[str, Any], expected: Sequence[str]
) -> list[str]:
    """Validate ordered per-replication execution identity against independent controls."""
    execution = _validate_execution_artifact_list(document["execution_artifact_sha256"])
    if execution != list(expected):
        raise EvidenceError("execution_artifact_sha256 does not match ordered control evidence")
    return execution


def _canonical_json_bytes(value: dict[str, Any]) -> bytes:
    """Encode one deterministic receipt so identity and publication use identical bytes."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _validate_predicate_for_receipt(raw: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    """Strictly validate the exact unsigned predicate semantics consumed by the signer handoff."""
    predicate = _load_strict_json_object(raw, "scientific-validation predicate JSON")
    _require_exact_keys(predicate, _REQUIRED_PREDICATE_KEYS, "scientific-validation predicate")
    _require_literal(predicate, "attestation_claim", "origin_and_integrity_only")
    if predicate["does_not_prove"] != _DOES_NOT_PROVE:
        raise EvidenceError("does_not_prove must preserve the owner scientific-boundary contract")
    _require_predicate_type(_require_string(predicate, "predicate_type"))
    _require_literal(predicate, "schema_version", _SCHEMA_VERSION)
    _require_repository(_require_string(predicate, "source_repository"))
    _require_git_sha(_require_string(predicate, "source_sha"))
    _require_positive_integer(_require_string(predicate, "workflow_run_id"), "workflow run ID")

    evidence = predicate["evidence"]
    if not isinstance(evidence, dict):
        raise EvidenceError("predicate evidence must be a JSON object")
    _require_exact_keys(evidence, _REQUIRED_PREDICATE_EVIDENCE_KEYS, "predicate evidence")
    _require_artifact_digest(_require_string(evidence, "artifact_digest"))
    _require_positive_integer(_require_string(evidence, "artifact_id"), "artifact ID")
    _require_artifact_name(_require_string(evidence, "artifact_name"))
    _require_positive_integer(
        _require_string(evidence, "artifact_size_in_bytes"), "artifact size in bytes"
    )
    _require_filename(_require_string(evidence, "evidence_filename"))
    for key in (
        "evidence_sha256",
        "exact_head_artifact_sha256",
        "exact_head_receipt_sha256",
        "profile_chronology_sha256",
        "profile_sha256",
        "recovery_evidence_sha256",
        "replication_provenance_sha256",
        "seed_manifest_sha256",
    ):
        _require_sha256(_require_string(evidence, key), key)
    _require_literal(evidence, "exact_head_status", "passed")
    _validate_execution_artifact_list(evidence["execution_artifact_sha256"])
    return predicate, evidence


def validate_receipt_manifest(raw: bytes, predicate_bytes: bytes) -> dict[str, Any]:
    """Validate one versioned completion marker against the exact predicate bytes it commits."""
    manifest = _load_strict_json_object(raw, "receipt manifest JSON")
    _require_exact_keys(manifest, _REQUIRED_MANIFEST_KEYS, "receipt manifest")
    _require_literal(manifest, "manifest_type", _MANIFEST_TYPE)
    _require_literal(manifest, "schema_version", _MANIFEST_SCHEMA_VERSION)
    artifact_digest = _require_artifact_digest(_require_string(manifest, "evidence_artifact_digest"))
    artifact_id = _require_positive_integer(
        _require_string(manifest, "evidence_artifact_id"), "artifact ID"
    )
    artifact_name = _require_artifact_name(_require_string(manifest, "evidence_artifact_name"))
    artifact_size_in_bytes = _require_positive_integer(
        _require_string(manifest, "evidence_artifact_size_in_bytes"), "artifact size in bytes"
    )
    evidence_filename = _require_filename(_require_string(manifest, "evidence_filename"))
    evidence_sha256 = _require_sha256(
        _require_string(manifest, "evidence_sha256"), "evidence SHA-256"
    )
    execution_artifacts = _validate_execution_artifact_list(manifest["execution_artifact_sha256"])
    predicate_sha256 = _require_sha256(
        _require_string(manifest, "predicate_sha256"), "predicate SHA-256"
    )
    predicate_type = _require_predicate_type(_require_string(manifest, "predicate_type"))
    source_repository = _require_repository(_require_string(manifest, "source_repository"))
    source_sha = _require_git_sha(_require_string(manifest, "source_sha"))
    _require_literal(manifest, "verification_result", "VALID")
    workflow_run_id = _require_positive_integer(
        _require_string(manifest, "workflow_run_id"), "workflow run ID"
    )

    actual_predicate_sha256 = hashlib.sha256(predicate_bytes).hexdigest()
    if predicate_sha256 != actual_predicate_sha256:
        raise EvidenceError("predicate SHA-256 does not match canonical predicate bytes")

    predicate, evidence = _validate_predicate_for_receipt(predicate_bytes)
    _require_manifest_predicate_binding(
        "source_repository", source_repository, predicate["source_repository"]
    )
    _require_manifest_predicate_binding("source_sha", source_sha, predicate["source_sha"])
    _require_manifest_predicate_binding(
        "workflow_run_id", workflow_run_id, predicate["workflow_run_id"]
    )
    _require_manifest_predicate_binding(
        "predicate_type", predicate_type, predicate["predicate_type"]
    )
    _require_manifest_predicate_binding(
        "evidence_artifact_digest", artifact_digest, evidence["artifact_digest"]
    )
    _require_manifest_predicate_binding("evidence_artifact_id", artifact_id, evidence["artifact_id"])
    _require_manifest_predicate_binding(
        "evidence_artifact_name", artifact_name, evidence["artifact_name"]
    )
    _require_manifest_predicate_binding(
        "evidence_artifact_size_in_bytes",
        artifact_size_in_bytes,
        evidence["artifact_size_in_bytes"],
    )
    _require_manifest_predicate_binding(
        "evidence_filename", evidence_filename, evidence["evidence_filename"]
    )
    _require_manifest_predicate_binding(
        "evidence_sha256", evidence_sha256, evidence["evidence_sha256"]
    )
    _require_manifest_predicate_binding(
        "execution_artifact_sha256",
        execution_artifacts,
        evidence["execution_artifact_sha256"],
    )
    return manifest


def _atomic_json_at(parent_descriptor: int, filename: str, value: dict[str, Any]) -> None:
    """Publish one canonical JSON receipt without clobbering a pre-existing output leaf."""
    _require_output_leaf_absent(parent_descriptor, filename)
    payload = _canonical_json_bytes(value)
    temporary = f".scientific-validation-{uuid.uuid4().hex}.tmp"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_descriptor,
        )
    except OSError as error:
        raise EvidenceError("temporary output creation failed") from error
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.fchmod(descriptor, 0o644)
        try:
            os.link(
                temporary,
                filename,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError as error:
            raise EvidenceError("output leaf must not already exist") from error
        except OSError as error:
            raise EvidenceError("output publication failed") from error
    finally:
        os.close(descriptor)
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent_descriptor)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    """Publish canonical JSON through a pinned unsymlinked parent directory."""
    _, parent_descriptor = _open_directory_without_symlinks(path.parent)
    try:
        _atomic_json_at(parent_descriptor, path.name, value)
    finally:
        os.close(parent_descriptor)


def verify(arguments: argparse.Namespace) -> dict[str, Any]:
    """Verify one sealed evidence document and emit deterministic unsigned intake receipts."""
    source_repository = _require_repository(arguments.source_repository)
    source_sha = _require_git_sha(arguments.source_sha)
    workflow_run_id = _require_positive_integer(arguments.workflow_run_id, "workflow run ID")
    artifact_id = _require_positive_integer(arguments.evidence_artifact_id, "artifact ID")
    artifact_name = _require_artifact_name(arguments.evidence_artifact_name)
    artifact_size_in_bytes = _require_positive_integer(
        arguments.evidence_artifact_size_in_bytes, "artifact size in bytes"
    )
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
        raise EvidenceError(
            "ordered control execution artifact identities must be at least two and distinct"
        )

    root, root_descriptor = _open_directory_without_symlinks(Path(arguments.evidence_root))
    predicate_descriptor: int | None = None
    manifest_descriptor: int | None = None
    shared_output_parent = False
    try:
        requested_predicate = Path(os.path.abspath(arguments.output_predicate))
        requested_manifest = Path(os.path.abspath(arguments.output_manifest))
        if requested_predicate == requested_manifest:
            raise EvidenceError("predicate and manifest must use distinct output paths")
        shared_output_parent = requested_predicate.parent == requested_manifest.parent

        output_predicate, predicate_descriptor = _validate_output_path(requested_predicate, root)
        if shared_output_parent:
            output_manifest = requested_manifest
            manifest_descriptor = predicate_descriptor
        else:
            output_manifest, manifest_descriptor = _validate_output_path(requested_manifest, root)
        _require_output_leaf_absent(predicate_descriptor, output_predicate.name)
        _require_output_leaf_absent(manifest_descriptor, output_manifest.name)

        members = os.listdir(root_descriptor)
        if len(members) != 1 or members[0] != evidence_filename:
            raise EvidenceError(
                "sealed scientific evidence cardinality must be exactly one named member"
            )
        evidence_bytes = _read_evidence_once(evidence_filename, dir_fd=root_descriptor)

        actual_evidence_sha256 = hashlib.sha256(evidence_bytes).hexdigest()
        if actual_evidence_sha256 != evidence_sha256:
            raise EvidenceError(
                f"evidence SHA-256 mismatch: expected {evidence_sha256}, got {actual_evidence_sha256}"
            )

        document = _load_document(evidence_bytes)
        _require_literal(document, "schema_version", _SCHEMA_VERSION)
        _require_document_binding(document, "source_repository", source_repository)
        _require_document_binding(document, "source_sha", source_sha)
        document_run_id = document["workflow_run_id"]
        if not isinstance(document_run_id, int) or isinstance(document_run_id, bool):
            raise EvidenceError("workflow_run_id must be a JSON integer")
        if str(document_run_id) != workflow_run_id:
            raise EvidenceError("workflow_run_id does not match the authenticated control value")
        for key, expected_value in expected.items():
            _require_document_binding(document, key, expected_value)
        _require_literal(document, "exact_head_status", "passed")
        execution_artifacts = _validate_execution_artifacts(document, expected_execution)

        predicate = {
            "attestation_claim": "origin_and_integrity_only",
            "does_not_prove": _DOES_NOT_PROVE.copy(),
            "evidence": {
                "artifact_digest": artifact_digest,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "artifact_size_in_bytes": artifact_size_in_bytes,
                "evidence_filename": evidence_filename,
                "evidence_sha256": evidence_sha256,
                "exact_head_artifact_sha256": expected["exact_head_artifact_sha256"],
                "exact_head_receipt_sha256": expected["exact_head_receipt_sha256"],
                "exact_head_status": "passed",
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
        predicate_bytes = _canonical_json_bytes(predicate)
        predicate_sha256 = hashlib.sha256(predicate_bytes).hexdigest()
        manifest = {
            "manifest_type": _MANIFEST_TYPE,
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "evidence_artifact_digest": artifact_digest,
            "evidence_artifact_id": artifact_id,
            "evidence_artifact_name": artifact_name,
            "evidence_artifact_size_in_bytes": artifact_size_in_bytes,
            "evidence_filename": evidence_filename,
            "evidence_sha256": evidence_sha256,
            "execution_artifact_sha256": execution_artifacts,
            "predicate_sha256": predicate_sha256,
            "predicate_type": predicate_type,
            "source_repository": source_repository,
            "source_sha": source_sha,
            "verification_result": "VALID",
            "workflow_run_id": workflow_run_id,
        }
        validate_receipt_manifest(_canonical_json_bytes(manifest), predicate_bytes)
        _atomic_json_at(predicate_descriptor, output_predicate.name, predicate)
        _atomic_json_at(manifest_descriptor, output_manifest.name, manifest)
        return manifest
    finally:
        os.close(root_descriptor)
        if manifest_descriptor is not None and not shared_output_parent:
            os.close(manifest_descriptor)
        if predicate_descriptor is not None:
            os.close(predicate_descriptor)


def _parser() -> argparse.ArgumentParser:
    """Create the strict command-line parser for scientific evidence intake."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--evidence-artifact-id", required=True)
    parser.add_argument("--evidence-artifact-name", required=True)
    parser.add_argument("--evidence-artifact-size-in-bytes", required=True)
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
