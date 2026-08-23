#!/usr/bin/env python3
"""Verify one sealed wheel/sdist/SBOM handoff without executing its contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import uuid
from pathlib import Path
from typing import Any, Iterable

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA1_RE = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_RE = re.compile(r"^(?!.*(?:\.\.|\.$|^\.))[A-Za-z0-9_.-]+/(?!.*(?:\.\.|\.$|^\.))[A-Za-z0-9_.-]+$")
_ARTIFACT_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_CHECKSUM_RE = re.compile(r"^([0-9a-f]{64}) [ *]([^/\\]+)$")
_MAX_JSON_BYTES = 16 * 1024 * 1024
_MAX_CONTROL_BYTES = 1024 * 1024
_SOURCE_IDENTITY = "source-identity.json"
_CHECKSUM_FILE = "checksums.sha256"
_FILENAME_PROPERTY = "cwl:artifact:filename"
_CYCLONEDX_PREDICATE_TYPE = "https://cyclonedx.org/bom"


class EvidenceError(ValueError):
    """Describe a deterministic sealed-evidence validation failure."""


def _reject_duplicate_keys(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
    """Build one JSON object while rejecting duplicate property names."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceError(f"duplicate JSON property: {key}")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> Any:
    """Reject JSON extensions for NaN and positive or negative infinity."""
    raise EvidenceError(f"non-finite JSON number is forbidden: {value}")


def _load_json(path: Path, maximum_bytes: int = _MAX_JSON_BYTES) -> Any:
    """Load strict bounded UTF-8 JSON from one regular non-symlink file."""
    _require_regular_file(path)
    if path.stat().st_size > maximum_bytes:
        raise EvidenceError(f"JSON file exceeds {maximum_bytes} bytes: {path.name}")
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
        return json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
        )
    except UnicodeError as error:
        raise EvidenceError(f"invalid UTF-8 in {path.name}") from error
    except json.JSONDecodeError as error:
        raise EvidenceError(f"invalid JSON in {path.name}: {error.msg}") from error


def _require_regular_file(path: Path) -> None:
    """Require one existing regular file with no symlink endpoint."""
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise EvidenceError(f"missing evidence file: {path.name}") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise EvidenceError(f"evidence member is not a regular file: {path.name}")


def _validate_filename(value: str, label: str) -> str:
    """Return a safe root-level evidence filename."""
    if not value or value in {".", ".."} or Path(value).name != value:
        raise EvidenceError(f"{label} must be one root-level filename")
    if "/" in value or "\\" in value or "\x00" in value:
        raise EvidenceError(f"{label} contains a forbidden path character")
    return value


def _validate_sha256(value: str, label: str) -> str:
    """Return one lowercase hexadecimal SHA-256 digest."""
    if not _SHA256_RE.fullmatch(value):
        raise EvidenceError(f"{label} must be 64 lowercase hexadecimal characters")
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
    """Require one file to match its externally supplied SHA-256 digest."""
    actual = _sha256(path)
    if actual != expected:
        raise EvidenceError(f"{label} digest mismatch: expected {expected}, got {actual}")


def _parse_checksums(path: Path) -> dict[str, str]:
    """Parse a canonical sorted GNU-style SHA-256 checksum file."""
    _require_regular_file(path)
    if path.stat().st_size > _MAX_CONTROL_BYTES:
        raise EvidenceError("checksum file exceeds the control-file size limit")
    try:
        lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
    except UnicodeError as error:
        raise EvidenceError("checksum file is not strict UTF-8") from error
    parsed: dict[str, str] = {}
    order: list[str] = []
    for line in lines:
        match = _CHECKSUM_RE.fullmatch(line)
        if match is None:
            raise EvidenceError("checksum file contains a noncanonical line")
        digest, filename = match.groups()
        if filename in parsed:
            raise EvidenceError(f"duplicate checksum filename: {filename}")
        parsed[filename] = digest
        order.append(filename)
    if order != sorted(order):
        raise EvidenceError("checksum entries must be sorted by filename")
    return parsed


def _cyclonedx_serial_number(subject_name: str, subject_sha256: str) -> str:
    """Return the canonical UUIDv5 serial number for one exact distribution."""
    identity = f"urn:cwl:artifact:{subject_name}:sha256:{subject_sha256}"
    return f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, identity)}"


def _validate_cyclonedx(
    path: Path,
    *,
    schema: str,
    subject_name: str,
    subject_sha256: str,
) -> None:
    """Validate a CycloneDX 1.7 document bound to one exact distribution."""
    document = _load_json(path)
    if not isinstance(document, dict):
        raise EvidenceError(f"{path.name} must contain a JSON object")
    if document.get("$schema") != schema:
        raise EvidenceError(f"{path.name} uses an unexpected CycloneDX schema")
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.7":
        raise EvidenceError(f"{path.name} must be CycloneDX specification 1.7")
    version = document.get("version")
    if (type(version), version) != (int, 1):
        raise EvidenceError(f"{path.name} document version must be the integer 1")
    expected_serial = _cyclonedx_serial_number(subject_name, subject_sha256)
    if document.get("serialNumber") != expected_serial:
        raise EvidenceError(f"{path.name} serial number does not match the exact subject")

    metadata = document.get("metadata")
    component = metadata.get("component") if isinstance(metadata, dict) else None
    if not isinstance(component, dict) or component.get("name") != subject_name:
        raise EvidenceError(f"{path.name} root component does not name {subject_name}")
    if component.get("type") != "file":
        raise EvidenceError(f"{path.name} root component type must be file")

    expected_property = {"name": _FILENAME_PROPERTY, "value": subject_name}
    if component.get("properties") != [expected_property]:
        raise EvidenceError(f"{path.name} root component filename property is not exact")

    expected_hash = {"alg": "SHA-256", "content": subject_sha256}
    if component.get("hashes") != [expected_hash]:
        raise EvidenceError(
            f"{path.name} root component must contain one canonical SHA-256 subject hash"
        )


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


def _validate_evidence_root(path: Path) -> Path:
    """Return an absolute evidence root after rejecting symlinked path components."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError as error:
            raise EvidenceError(
                "evidence root must be an existing non-symlink directory"
            ) from error
        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            raise EvidenceError(
                "evidence root and every ancestor must be non-symlink directories"
            )
    return absolute


def verify(arguments: argparse.Namespace) -> dict[str, Any]:
    """Validate exact evidence and return its deterministic verification manifest."""
    if not _REPOSITORY_RE.fullmatch(arguments.source_repository):
        raise EvidenceError("source repository must use owner/name form")
    if not _SHA1_RE.fullmatch(arguments.source_sha):
        raise EvidenceError("source SHA must be a lowercase 40-character Git SHA")
    if not _ARTIFACT_DIGEST_RE.fullmatch(arguments.evidence_artifact_digest):
        raise EvidenceError("evidence artifact digest must use sha256:<hex>")
    if arguments.predicate_type != _CYCLONEDX_PREDICATE_TYPE:
        raise EvidenceError(
            "predicate type must be the canonical CycloneDX predicate "
            f"{_CYCLONEDX_PREDICATE_TYPE}"
        )

    root = _validate_evidence_root(Path(arguments.evidence_root))

    names = {
        "wheel": _validate_filename(arguments.wheel_filename, "wheel filename"),
        "wheel_sbom": _validate_filename(
            arguments.wheel_sbom_filename, "wheel SBOM filename"
        ),
        "sdist": _validate_filename(arguments.sdist_filename, "sdist filename"),
        "sdist_sbom": _validate_filename(
            arguments.sdist_sbom_filename, "sdist SBOM filename"
        ),
        "source_identity": _SOURCE_IDENTITY,
        "checksums": _CHECKSUM_FILE,
    }
    if len(set(names.values())) != len(names):
        raise EvidenceError("all six evidence filenames must be distinct")

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

    expected_digests = {
        names["wheel"]: _validate_sha256(arguments.wheel_sha256, "wheel SHA-256"),
        names["wheel_sbom"]: _validate_sha256(
            arguments.wheel_sbom_sha256, "wheel SBOM SHA-256"
        ),
        names["sdist"]: _validate_sha256(arguments.sdist_sha256, "sdist SHA-256"),
        names["sdist_sbom"]: _validate_sha256(
            arguments.sdist_sbom_sha256, "sdist SBOM SHA-256"
        ),
        names["source_identity"]: _validate_sha256(
            arguments.source_identity_sha256, "source identity SHA-256"
        ),
        names["checksums"]: _validate_sha256(
            arguments.checksum_sha256, "checksum SHA-256"
        ),
    }
    for filename, expected in expected_digests.items():
        _require_digest(root / filename, expected, filename)

    checksums = _parse_checksums(root / names["checksums"])
    checksum_subjects = expected_members - {names["checksums"]}
    if set(checksums) != checksum_subjects:
        raise EvidenceError("checksum file must bind exactly the other five evidence files")
    for filename in checksum_subjects:
        if checksums[filename] != expected_digests[filename]:
            raise EvidenceError(f"checksum handoff mismatch for {filename}")

    identity = _load_json(root / names["source_identity"], _MAX_CONTROL_BYTES)
    if not isinstance(identity, dict):
        raise EvidenceError("source identity must contain a JSON object")
    expected_identity = {
        "schema_version": "1.0",
        "source_repository": arguments.source_repository,
        "source_sha": arguments.source_sha,
        "evidence_artifact_name": arguments.evidence_artifact_name,
        "evidence_artifact_digest": arguments.evidence_artifact_digest,
        "predicate_type": arguments.predicate_type,
        "cyclonedx_schema": arguments.cyclonedx_schema,
        "artifacts": {
            "wheel": {
                "filename": names["wheel"],
                "sha256": expected_digests[names["wheel"]],
                "sbom_filename": names["wheel_sbom"],
                "sbom_sha256": expected_digests[names["wheel_sbom"]],
            },
            "sdist": {
                "filename": names["sdist"],
                "sha256": expected_digests[names["sdist"]],
                "sbom_filename": names["sdist_sbom"],
                "sbom_sha256": expected_digests[names["sdist_sbom"]],
            },
        },
    }
    if identity != expected_identity:
        raise EvidenceError("source identity does not exactly match the sealed handoff")

    _validate_cyclonedx(
        root / names["wheel_sbom"],
        schema=arguments.cyclonedx_schema,
        subject_name=names["wheel"],
        subject_sha256=expected_digests[names["wheel"]],
    )
    _validate_cyclonedx(
        root / names["sdist_sbom"],
        schema=arguments.cyclonedx_schema,
        subject_name=names["sdist"],
        subject_sha256=expected_digests[names["sdist"]],
    )

    manifest = {
        "result": "PASS",
        "source_repository": arguments.source_repository,
        "source_sha": arguments.source_sha,
        "predicate_type": arguments.predicate_type,
        "cyclonedx_schema": arguments.cyclonedx_schema,
        "files": [
            {
                "filename": filename,
                "sha256": expected_digests[filename],
                "size_bytes": (root / filename).stat().st_size,
            }
            for filename in sorted(expected_members)
        ],
    }
    _atomic_json(Path(arguments.output_manifest), manifest)
    return manifest


def _parser() -> argparse.ArgumentParser:
    """Create the strict command-line parser for sealed handoff verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--evidence-artifact-name", required=True)
    parser.add_argument("--evidence-artifact-digest", required=True)
    parser.add_argument("--evidence-root", required=True)
    parser.add_argument("--wheel-filename", required=True)
    parser.add_argument("--wheel-sha256", required=True)
    parser.add_argument("--wheel-sbom-filename", required=True)
    parser.add_argument("--wheel-sbom-sha256", required=True)
    parser.add_argument("--sdist-filename", required=True)
    parser.add_argument("--sdist-sha256", required=True)
    parser.add_argument("--sdist-sbom-filename", required=True)
    parser.add_argument("--sdist-sbom-sha256", required=True)
    parser.add_argument("--source-identity-sha256", required=True)
    parser.add_argument("--checksum-sha256", required=True)
    parser.add_argument("--predicate-type", required=True)
    parser.add_argument("--cyclonedx-schema", required=True)
    parser.add_argument("--output-manifest", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run sealed-evidence verification and emit one compact decision line."""
    arguments = _parser().parse_args(argv)
    try:
        manifest = verify(arguments)
    except EvidenceError as error:
        raise SystemExit(f"sealed evidence verification failed: {error}") from error
    print(
        "sealed evidence verification passed: "
        f"{len(manifest['files'])} files at {manifest['source_sha']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
