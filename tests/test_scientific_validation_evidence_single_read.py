"""Hostile contracts for one-read evidence identity and atomic output refusal."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci import verify_scientific_validation_evidence as verifier

PREDICATE = "https://contextualwisdomlab.org/attestations/scientific-validation/v1"
EXECUTION = ["8" * 64, "9" * 64]


def _sha256_bytes(value: bytes) -> str:
    """Hash fixture bytes without relying on the production intake helper."""
    return hashlib.sha256(value).hexdigest()


def _document() -> dict[str, object]:
    """Return one valid represented scientific-validation evidence document."""
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
        "execution_artifact_sha256": EXECUTION.copy(),
    }


def _arguments(tmp_path: Path, evidence_sha256: str) -> argparse.Namespace:
    """Build the independent control plane for one sealed evidence member."""
    return argparse.Namespace(
        source_repository="ContextualWisdomLab/TEPP",
        source_sha="a" * 40,
        workflow_run_id="123456",
        evidence_artifact_id="777",
        evidence_artifact_name="scientific-validation-evidence",
        evidence_artifact_digest="sha256:" + ("b" * 64),
        evidence_root=str(tmp_path / "sealed"),
        evidence_filename="scientific-validation-evidence.json",
        evidence_sha256=evidence_sha256,
        profile_sha256="1" * 64,
        profile_chronology_sha256="2" * 64,
        exact_head_receipt_sha256="3" * 64,
        exact_head_artifact_sha256="4" * 64,
        seed_manifest_sha256="5" * 64,
        recovery_evidence_sha256="6" * 64,
        replication_provenance_sha256="7" * 64,
        execution_artifact_sha256=EXECUTION.copy(),
        predicate_type=PREDICATE,
        output_predicate=str(tmp_path / "predicate.json"),
        output_manifest=str(tmp_path / "manifest.json"),
    )


def test_evidence_digest_and_semantics_are_derived_from_one_byte_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never hash one path state and validate a later replacement through the same name."""
    root = tmp_path / "sealed"
    root.mkdir()
    evidence = root / "scientific-validation-evidence.json"
    valid_bytes = (
        json.dumps(_document(), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    malicious_bytes = valid_bytes.replace(
        b'{"exact_head_artifact_sha256"',
        b'{"schema_version":"1.0","exact_head_artifact_sha256"',
        1,
    )
    evidence.write_bytes(malicious_bytes)
    arguments = _arguments(tmp_path, _sha256_bytes(malicious_bytes))
    original_read_text = Path.read_text
    swapped = False

    def swap_then_read(path: Path, *args: object, **kwargs: object) -> str:
        nonlocal swapped
        if path == evidence and not swapped:
            swapped = True
            evidence.write_bytes(valid_bytes)
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", swap_then_read)
    with pytest.raises(verifier.EvidenceError, match="duplicate JSON property"):
        verifier.verify(arguments)

    assert not Path(arguments.output_predicate).exists()
    assert not Path(arguments.output_manifest).exists()


def test_atomic_writer_rejects_symlink_leaf_without_mutating_target(tmp_path: Path) -> None:
    """Exercise the atomic writer's own leaf-symlink guard, not an earlier verifier guard."""
    target = tmp_path / "target.json"
    target.write_text("original\n", encoding="utf-8")
    output = tmp_path / "output.json"
    output.symlink_to(target)

    with pytest.raises(verifier.EvidenceError, match="output path must not be a symbolic link"):
        verifier._atomic_json(output, {"replacement": True})

    assert target.read_text(encoding="utf-8") == "original\n"
