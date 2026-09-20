"""Filesystem-authority contracts for scientific-validation verifier outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci import verify_scientific_validation_evidence as verifier

_PREDICATE = "https://contextualwisdomlab.org/attestations/scientific-validation/v1"
_EXECUTION = ["8" * 64, "9" * 64]


def _write_json(path: Path, value: object) -> None:
    """Write one deterministic JSON fixture."""
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _arguments(tmp_path: Path) -> argparse.Namespace:
    """Build one valid sealed-evidence invocation for output-boundary tests."""
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


def test_output_parent_symlink_is_rejected(tmp_path: Path) -> None:
    """Do not publish verifier output through a symlinked directory ancestor."""
    arguments = _arguments(tmp_path)
    real = tmp_path / "real-output"
    real.mkdir()
    alias = tmp_path / "output-alias"
    alias.symlink_to(real, target_is_directory=True)
    arguments.output_predicate = str(alias / "predicate.json")

    with pytest.raises(verifier.EvidenceError, match="output.*symlink"):
        verifier.verify(arguments)

    assert list(real.iterdir()) == []


def test_predicate_and_manifest_must_use_distinct_paths(tmp_path: Path) -> None:
    """Prevent the manifest publication from replacing the verified predicate."""
    arguments = _arguments(tmp_path)
    arguments.output_manifest = arguments.output_predicate

    with pytest.raises(verifier.EvidenceError, match="distinct output paths"):
        verifier.verify(arguments)

    assert not Path(arguments.output_predicate).exists()


def test_outputs_cannot_mutate_the_sealed_evidence_root(tmp_path: Path) -> None:
    """Keep the verified one-member evidence set immutable after validation."""
    arguments = _arguments(tmp_path)
    root = Path(arguments.evidence_root)
    arguments.output_predicate = str(root / "predicate.json")

    with pytest.raises(verifier.EvidenceError, match="outside the sealed evidence root"):
        verifier.verify(arguments)

    assert [member.name for member in root.iterdir()] == [arguments.evidence_filename]
