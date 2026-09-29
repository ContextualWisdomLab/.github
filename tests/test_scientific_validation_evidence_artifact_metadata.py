"""Contracts for immutable GitHub artifact metadata in scientific-validation receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci import verify_scientific_validation_evidence as verifier

_PREDICATE = "https://contextualwisdomlab.org/attestations/scientific-validation/v1"
_EXECUTION = ["8" * 64, "9" * 64]
_ARTIFACT_SIZE = "556"


def _write_json(path: Path, value: object) -> None:
    """Write deterministic fixture JSON."""
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _arguments(tmp_path: Path) -> argparse.Namespace:
    """Build one valid invocation with independently supplied artifact metadata."""
    root = tmp_path / "sealed"
    root.mkdir(parents=True)
    evidence = root / "scientific-validation-evidence.json"
    document = {
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
        "execution_artifact_sha256": _EXECUTION.copy(),
    }
    _write_json(evidence, document)
    return argparse.Namespace(
        source_repository="ContextualWisdomLab/TEPP",
        source_sha="a" * 40,
        workflow_run_id="123456",
        evidence_artifact_id="777",
        evidence_artifact_name="scientific-validation-evidence",
        evidence_artifact_size_in_bytes=_ARTIFACT_SIZE,
        evidence_artifact_digest="sha256:" + ("b" * 64),
        evidence_root=str(root),
        evidence_filename=evidence.name,
        evidence_sha256=hashlib.sha256(evidence.read_bytes()).hexdigest(),
        profile_sha256="1" * 64,
        profile_chronology_sha256="2" * 64,
        exact_head_receipt_sha256="3" * 64,
        exact_head_artifact_sha256="4" * 64,
        seed_manifest_sha256="5" * 64,
        recovery_evidence_sha256="6" * 64,
        replication_provenance_sha256="7" * 64,
        execution_artifact_sha256=_EXECUTION.copy(),
        predicate_type=_PREDICATE,
        output_predicate=str(tmp_path / "predicate.json"),
        output_manifest=str(tmp_path / "manifest.json"),
    )


def test_receipt_binds_live_artifact_size_metadata(tmp_path: Path) -> None:
    """Commit GitHub artifact size beside ID, name, and digest in both receipt layers."""
    arguments = _arguments(tmp_path)

    manifest = verifier.verify(arguments)
    predicate = json.loads(Path(arguments.output_predicate).read_text(encoding="utf-8"))

    assert predicate["evidence"]["artifact_size_in_bytes"] == _ARTIFACT_SIZE
    assert manifest["evidence_artifact_size_in_bytes"] == _ARTIFACT_SIZE


@pytest.mark.parametrize("invalid_size", ["0", "-1", "+1", "1.0", "1e3", "abc"])
def test_artifact_size_control_is_positive_decimal_metadata(
    tmp_path: Path, invalid_size: str
) -> None:
    """Reject malformed artifact-size controls instead of coercing or inferring them."""
    arguments = _arguments(tmp_path)
    arguments.evidence_artifact_size_in_bytes = invalid_size

    with pytest.raises(verifier.EvidenceError, match="artifact size in bytes"):
        verifier.verify(arguments)


def test_receipt_manifest_rejects_conflicting_artifact_size(tmp_path: Path) -> None:
    """Reject a versioned manifest whose artifact size contradicts its committed predicate."""
    arguments = _arguments(tmp_path)
    manifest = verifier.verify(arguments)
    predicate_bytes = Path(arguments.output_predicate).read_bytes()
    contradictory = dict(manifest)
    contradictory["evidence_artifact_size_in_bytes"] = "557"

    with pytest.raises(verifier.EvidenceError, match="evidence_artifact_size_in_bytes.*predicate"):
        verifier.validate_receipt_manifest(
            verifier._canonical_json_bytes(contradictory), predicate_bytes
        )


def test_artifact_size_is_not_inferred_from_extracted_evidence_bytes(tmp_path: Path) -> None:
    """Preserve artifact size as authenticated GitHub metadata, not member-file byte length."""
    arguments = _arguments(tmp_path)
    evidence = Path(arguments.evidence_root, arguments.evidence_filename)
    assert str(len(evidence.read_bytes())) != _ARTIFACT_SIZE

    manifest = verifier.verify(arguments)

    assert manifest["evidence_artifact_size_in_bytes"] == _ARTIFACT_SIZE
