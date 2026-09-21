"""Hostile-file and byte-bound contracts for the scientific-validation signer handoff."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
from pathlib import Path

import pytest

from scripts.ci import validate_scientific_validation_receipt as receipt


EXECUTION = ["8" * 64, "9" * 64]


def _canonical(value: dict[str, object]) -> bytes:
    """Encode fixture JSON without depending on the production encoder."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _valid_pair(tmp_path: Path) -> tuple[Path, Path, dict[str, object]]:
    """Write one semantically valid manifest/predicate pair for bounded-file tests."""
    tmp_path.mkdir(parents=True, exist_ok=True)
    predicate: dict[str, object] = {
        "attestation_claim": "origin_and_integrity_only",
        "does_not_prove": [
            "psychometric_numerical_acceptance",
            "rmse_or_bias_threshold_passed",
            "construct_validity",
            "estimator_validity",
            "production_equivalence",
        ],
        "evidence": {
            "artifact_digest": "sha256:" + ("b" * 64),
            "artifact_id": "777",
            "artifact_name": "scientific-validation-evidence",
            "artifact_size_in_bytes": "556",
            "evidence_filename": "scientific-validation-evidence.json",
            "evidence_sha256": "0" * 64,
            "exact_head_artifact_sha256": "4" * 64,
            "exact_head_receipt_sha256": "3" * 64,
            "exact_head_status": "passed",
            "execution_artifact_sha256": EXECUTION.copy(),
            "profile_chronology_sha256": "2" * 64,
            "profile_sha256": "1" * 64,
            "recovery_evidence_sha256": "6" * 64,
            "replication_provenance_sha256": "7" * 64,
            "seed_manifest_sha256": "5" * 64,
        },
        "predicate_type": "https://contextualwisdomlab.org/attestations/scientific-validation/v1",
        "schema_version": "1.0",
        "source_repository": "ContextualWisdomLab/TEPP",
        "source_sha": "a" * 40,
        "workflow_run_id": "123456",
    }
    predicate_bytes = _canonical(predicate)
    manifest: dict[str, object] = {
        "manifest_type": "https://contextualwisdomlab.org/attestations/scientific-validation-manifest/v1",
        "schema_version": "1.0",
        "evidence_artifact_digest": "sha256:" + ("b" * 64),
        "evidence_artifact_id": "777",
        "evidence_artifact_name": "scientific-validation-evidence",
        "evidence_artifact_size_in_bytes": "556",
        "evidence_filename": "scientific-validation-evidence.json",
        "evidence_sha256": "0" * 64,
        "execution_artifact_sha256": EXECUTION.copy(),
        "predicate_sha256": hashlib.sha256(predicate_bytes).hexdigest(),
        "predicate_type": "https://contextualwisdomlab.org/attestations/scientific-validation/v1",
        "source_repository": "ContextualWisdomLab/TEPP",
        "source_sha": "a" * 40,
        "verification_result": "VALID",
        "workflow_run_id": "123456",
    }
    manifest_path = tmp_path / "manifest.json"
    predicate_path = tmp_path / "predicate.json"
    manifest_path.write_bytes(_canonical(manifest))
    predicate_path.write_bytes(predicate_bytes)
    return manifest_path, predicate_path, manifest


def test_valid_receipt_pair_preserves_exact_bytes_for_semantic_validation(tmp_path: Path) -> None:
    """Accept the canonical pair while delegating meaning to the existing owner validator."""
    manifest_path, predicate_path, expected = _valid_pair(tmp_path)

    assert receipt.validate_receipt_files(manifest_path, predicate_path) == expected


def test_valid_receipt_pair_may_use_two_distinct_pinned_parents(tmp_path: Path) -> None:
    """Keep distinct-parent receipt support while pinning both authorities before intake."""
    manifest, _, expected = _valid_pair(tmp_path / "manifest-parent")
    _, predicate, _ = _valid_pair(tmp_path / "predicate-parent")

    assert receipt.validate_receipt_files(manifest, predicate) == expected


def test_manifest_and_predicate_are_bounded_before_semantic_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject oversized raw receipt files before JSON parsing or hashing can consume them."""
    monkeypatch.setattr(receipt, "_MAX_RECEIPT_BYTES", 4)
    manifest = tmp_path / "manifest.json"
    predicate = tmp_path / "predicate.json"

    manifest.write_bytes(b"12345")
    predicate.write_bytes(b"{}")
    with pytest.raises(receipt.EvidenceError, match="receipt manifest exceeds 4 bytes"):
        receipt.validate_receipt_files(manifest, predicate)

    manifest.write_bytes(b"{}")
    predicate.write_bytes(b"12345")
    with pytest.raises(receipt.EvidenceError, match="scientific-validation predicate exceeds 4 bytes"):
        receipt.validate_receipt_files(manifest, predicate)


def test_missing_symlink_nonregular_and_parent_symlink_receipts_fail_closed(tmp_path: Path) -> None:
    """Keep hostile filesystem objects outside the signer semantic parser."""
    manifest, predicate, _ = _valid_pair(tmp_path)
    manifest.unlink()
    with pytest.raises(receipt.EvidenceError, match="receipt manifest must be an existing regular file"):
        receipt.validate_receipt_files(manifest, predicate)

    target = tmp_path / "target.json"
    target.write_bytes(b"{}")
    manifest.symlink_to(target)
    with pytest.raises(receipt.EvidenceError, match="receipt manifest must be an existing regular file"):
        receipt.validate_receipt_files(manifest, predicate)
    manifest.unlink()

    manifest.mkdir()
    with pytest.raises(receipt.EvidenceError, match="receipt manifest must be an existing regular file"):
        receipt.validate_receipt_files(manifest, predicate)
    manifest.rmdir()

    fifo = tmp_path / "manifest.fifo"
    os.mkfifo(fifo)
    with pytest.raises(receipt.EvidenceError, match="receipt manifest must be an existing regular file"):
        receipt.validate_receipt_files(fifo, predicate)

    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias_parent = tmp_path / "alias"
    alias_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(receipt.EvidenceError, match="unsymlinked directories"):
        receipt.validate_receipt_files(alias_parent / "manifest.json", predicate)


def test_receipt_paths_must_be_distinct(tmp_path: Path) -> None:
    """Do not permit one pathname to masquerade as both completion marker and predicate."""
    manifest, _, _ = _valid_pair(tmp_path)
    with pytest.raises(receipt.EvidenceError, match="must use distinct paths"):
        receipt.validate_receipt_files(manifest, manifest)


def test_receipt_inodes_must_be_distinct_before_semantic_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject different hard-link names for one inode before receipt semantics are evaluated."""
    manifest, predicate, _ = _valid_pair(tmp_path)
    predicate.unlink()
    os.link(manifest, predicate)

    def _must_not_parse(_manifest_bytes: bytes, _predicate_bytes: bytes) -> dict[str, object]:
        raise AssertionError("semantic validation must not receive one inode in both receipt roles")

    monkeypatch.setattr(receipt.verifier, "validate_receipt_manifest", _must_not_parse)
    with pytest.raises(receipt.EvidenceError, match="must use distinct regular-file inodes"):
        receipt.validate_receipt_files(manifest, predicate)


def test_receipt_parent_authority_is_pinned_before_either_leaf_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject a pair assembled by swapping one shared receipt directory between leaf reads."""
    receipt_dir = tmp_path / "receipt"
    manifest, predicate, _ = _valid_pair(receipt_dir)
    predicate.write_bytes(b"{}")

    replacement_dir = tmp_path / "replacement"
    _valid_pair(replacement_dir)
    held_dir = tmp_path / "held"
    original_open_parent = receipt.verifier._open_directory_without_symlinks
    parent_open_count = 0

    def _swap_before_second_parent_open(path: Path) -> tuple[Path, int]:
        nonlocal parent_open_count
        parent_open_count += 1
        if parent_open_count == 2:
            receipt_dir.rename(held_dir)
            replacement_dir.rename(receipt_dir)
        return original_open_parent(path)

    monkeypatch.setattr(
        receipt.verifier,
        "_open_directory_without_symlinks",
        _swap_before_second_parent_open,
    )

    with pytest.raises(receipt.EvidenceError, match="predicate SHA-256"):
        receipt.validate_receipt_files(manifest, predicate)


def test_semantically_invalid_bounded_pair_is_still_rejected(tmp_path: Path) -> None:
    """Keep byte bounds as a precondition rather than a substitute for semantic validation."""
    manifest, predicate, _ = _valid_pair(tmp_path)
    parsed = json.loads(manifest.read_text(encoding="utf-8"))
    parsed["verification_result"] = "FAILED"
    manifest.write_bytes(_canonical(parsed))

    with pytest.raises(receipt.EvidenceError, match="verification_result must be VALID"):
        receipt.validate_receipt_files(manifest, predicate)


def test_cli_success_failure_and_script_dispatch_are_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise the signer-facing command boundary and executable dispatch."""
    manifest, predicate, _ = _valid_pair(tmp_path)
    argv = ["--receipt-manifest", str(manifest), "--predicate", str(predicate)]
    assert receipt.main(argv) == 0

    manifest.unlink()
    assert receipt.main(argv) == 2
    assert "scientific validation receipt rejected" in capsys.readouterr().err

    manifest, predicate, _ = _valid_pair(tmp_path / "dispatch")
    monkeypatch.setattr(
        "sys.argv",
        [
            str(Path(receipt.__file__)),
            "--receipt-manifest",
            str(manifest),
            "--predicate",
            str(predicate),
        ],
    )
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(Path(receipt.__file__)), run_name="__main__")


def test_loader_fails_closed_when_sibling_verifier_cannot_be_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cover the immutable-owner bootstrap refusal instead of silently importing elsewhere."""
    monkeypatch.setattr(receipt.importlib.util, "spec_from_file_location", lambda *_args: None)
    with pytest.raises(RuntimeError, match="could not be loaded"):
        receipt._load_verifier_module()
