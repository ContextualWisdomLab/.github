"""Public RED contracts for sealed scientific-validation evidence verification."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci import verify_scientific_validation_evidence as verifier

PREDICATE = "https://contextualwisdomlab.org/attestations/scientific-validation/v1"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "source_repository": "ContextualWisdomLab/TEPP",
        "source_sha": "a" * 40,
        "workflow_run_id": 123456,
        "profile_sha256": "1" * 64,
        "profile_chronology_sha256": "2" * 64,
        "exact_head_receipt_sha256": "3" * 64,
        "exact_head_artifact_sha256": "4" * 64,
        "exact_head_status": "passed",
        "seed_manifest_sha256": "5" * 64,
        "recovery_evidence_sha256": "6" * 64,
        "replication_provenance_sha256": "7" * 64,
        "execution_artifact_sha256": ["8" * 64, "9" * 64],
    }


def _valid(tmp_path: Path) -> argparse.Namespace:
    root = tmp_path / "sealed"
    root.mkdir()
    evidence = root / "scientific-validation-evidence.json"
    _write_json(evidence, _document())
    return argparse.Namespace(
        source_repository="ContextualWisdomLab/TEPP",
        source_sha="a" * 40,
        workflow_run_id="123456",
        evidence_artifact_id="777",
        evidence_artifact_name="scientific-validation-evidence",
        evidence_artifact_digest="sha256:" + ("b" * 64),
        evidence_root=str(root),
        evidence_filename=evidence.name,
        evidence_sha256=_sha256_bytes(evidence.read_bytes()),
        profile_sha256="1" * 64,
        profile_chronology_sha256="2" * 64,
        exact_head_receipt_sha256="3" * 64,
        exact_head_artifact_sha256="4" * 64,
        seed_manifest_sha256="5" * 64,
        recovery_evidence_sha256="6" * 64,
        replication_provenance_sha256="7" * 64,
        predicate_type=PREDICATE,
        output_predicate=str(tmp_path / "predicate.json"),
        output_manifest=str(tmp_path / "manifest.json"),
    )


def test_valid_sealed_evidence_is_verified_deterministically(tmp_path: Path) -> None:
    arguments = _valid(tmp_path)
    first = verifier.verify(arguments)
    first_predicate = Path(arguments.output_predicate).read_bytes()
    first_manifest = Path(arguments.output_manifest).read_bytes()

    second = verifier.verify(arguments)

    assert first == second
    assert Path(arguments.output_predicate).read_bytes() == first_predicate
    assert Path(arguments.output_manifest).read_bytes() == first_manifest
    assert first["verification_result"] == "VALID"
    assert first["source_sha"] == arguments.source_sha
    assert first["predicate_type"] == PREDICATE
    assert first["execution_artifact_sha256"] == ["8" * 64, "9" * 64]


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("source_repository", "not-a-repository", "owner/name"),
        ("source_sha", "A" * 40, "lowercase 40-character"),
        ("workflow_run_id", "0", "positive decimal"),
        ("evidence_artifact_id", "not-an-id", "positive decimal"),
        ("evidence_artifact_digest", "sha256:nope", "artifact digest"),
        ("predicate_type", "https://example.invalid/predicate", "predicate type"),
        ("profile_sha256", "0" * 63, "profile SHA-256"),
        ("exact_head_receipt_sha256", "G" * 64, "exact-head receipt SHA-256"),
    ],
)
def test_malformed_external_control_plane_identity_fails_closed(
    tmp_path: Path, attribute: str, value: str, message: str
) -> None:
    arguments = _valid(tmp_path)
    setattr(arguments, attribute, value)
    with pytest.raises(verifier.EvidenceError, match=message):
        verifier.verify(arguments)


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("source_repository", "ContextualWisdomLab/other", "source_repository"),
        ("source_sha", "f" * 40, "source_sha"),
        ("workflow_run_id", 654321, "workflow_run_id"),
        ("profile_sha256", "a" * 64, "profile_sha256"),
        ("profile_chronology_sha256", "a" * 64, "profile_chronology_sha256"),
        ("exact_head_receipt_sha256", "a" * 64, "exact_head_receipt_sha256"),
        ("exact_head_artifact_sha256", "a" * 64, "exact_head_artifact_sha256"),
        ("seed_manifest_sha256", "a" * 64, "seed_manifest_sha256"),
        ("recovery_evidence_sha256", "a" * 64, "recovery_evidence_sha256"),
        ("replication_provenance_sha256", "a" * 64, "replication_provenance_sha256"),
        ("exact_head_status", "failed", "exact_head_status"),
    ],
)
def test_resealed_semantic_substitution_fails_closed(
    tmp_path: Path, key: str, value: object, message: str
) -> None:
    arguments = _valid(tmp_path)
    evidence = Path(arguments.evidence_root, arguments.evidence_filename)
    document = _document()
    document[key] = value
    _write_json(evidence, document)
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())

    with pytest.raises(verifier.EvidenceError, match=message):
        verifier.verify(arguments)


def test_reordered_or_substituted_execution_artifacts_fail_closed(tmp_path: Path) -> None:
    arguments = _valid(tmp_path)
    evidence = Path(arguments.evidence_root, arguments.evidence_filename)
    document = _document()
    document["execution_artifact_sha256"] = ["9" * 64, "8" * 64]
    _write_json(evidence, document)
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())

    with pytest.raises(verifier.EvidenceError, match="execution_artifact_sha256"):
        verifier.verify(arguments)


def test_duplicate_execution_artifact_identity_fails_closed(tmp_path: Path) -> None:
    arguments = _valid(tmp_path)
    evidence = Path(arguments.evidence_root, arguments.evidence_filename)
    document = _document()
    document["execution_artifact_sha256"] = ["8" * 64, "8" * 64]
    _write_json(evidence, document)
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())

    with pytest.raises(verifier.EvidenceError, match="distinct"):
        verifier.verify(arguments)


def test_extra_evidence_member_and_symlink_fail_closed(tmp_path: Path) -> None:
    arguments = _valid(tmp_path)
    root = Path(arguments.evidence_root)
    (root / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(verifier.EvidenceError, match="cardinality"):
        verifier.verify(arguments)

    (root / "unexpected.txt").unlink()
    target = tmp_path / "outside.json"
    target.write_text("{}\n", encoding="utf-8")
    (root / "alias.json").symlink_to(target)
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier.verify(arguments)


def test_digest_mismatch_fails_even_when_document_is_otherwise_valid(tmp_path: Path) -> None:
    arguments = _valid(tmp_path)
    arguments.evidence_sha256 = "f" * 64
    with pytest.raises(verifier.EvidenceError, match="evidence SHA-256 mismatch"):
        verifier.verify(arguments)
