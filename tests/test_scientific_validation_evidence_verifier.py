"""Behavior, hostile-input, and branch contracts for scientific evidence intake."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import runpy
from pathlib import Path

import pytest

from scripts.ci import verify_scientific_validation_evidence as verifier

PREDICATE = "https://contextualwisdomlab.org/attestations/scientific-validation/v1"
EXECUTION = ["8" * 64, "9" * 64]


def _sha256_bytes(value: bytes) -> str:
    """Hash fixture bytes without depending on the production helper."""
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    """Write deterministic strict fixture JSON."""
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def _document() -> dict[str, object]:
    """Return the canonical sealed scientific-validation evidence document."""
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


def _valid(tmp_path: Path) -> argparse.Namespace:
    """Create one valid single-member sealed evidence set and its controls."""
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
        execution_artifact_sha256=EXECUTION.copy(),
        predicate_type=PREDICATE,
        output_predicate=str(tmp_path / "predicate.json"),
        output_manifest=str(tmp_path / "manifest.json"),
    )


def _reseal(arguments: argparse.Namespace, document: object) -> None:
    """Rewrite the evidence bytes and update only their external file digest."""
    evidence = Path(arguments.evidence_root, arguments.evidence_filename)
    _write_json(evidence, document)
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())


def _argv(arguments: argparse.Namespace) -> list[str]:
    """Translate fixture controls to the public CLI form."""
    result: list[str] = []
    for name, value in vars(arguments).items():
        option = "--" + name.replace("_", "-")
        if isinstance(value, list):
            for member in value:
                result.extend((option, member))
        else:
            result.extend((option, str(value)))
    return result


def test_valid_sealed_evidence_is_verified_deterministically(tmp_path: Path) -> None:
    """Bind every represented identity while keeping output byte-stable."""
    arguments = _valid(tmp_path)
    first = verifier.verify(arguments)
    first_predicate = Path(arguments.output_predicate).read_bytes()
    first_manifest = Path(arguments.output_manifest).read_bytes()

    second = verifier.verify(arguments)
    predicate = json.loads(first_predicate)

    assert first == second
    assert Path(arguments.output_predicate).read_bytes() == first_predicate
    assert Path(arguments.output_manifest).read_bytes() == first_manifest
    assert first["verification_result"] == "VALID"
    assert first["source_sha"] == arguments.source_sha
    assert first["predicate_type"] == PREDICATE
    assert first["execution_artifact_sha256"] == EXECUTION
    assert predicate["attestation_claim"] == "origin_and_integrity_only"
    assert predicate["evidence"]["profile_chronology_sha256"] == "2" * 64
    assert "psychometric_numerical_acceptance" in predicate["does_not_prove"]


def test_public_cli_success_and_failure_are_stable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Exercise both command-line exit contracts without exception translation drift."""
    arguments = _valid(tmp_path)
    assert verifier.main(_argv(arguments)) == 0

    arguments.source_sha = "A" * 40
    assert verifier.main(_argv(arguments)) == 2
    assert "scientific validation evidence rejected" in capsys.readouterr().err


def test_script_dispatch_calls_main(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the executable module boundary used by the reusable workflow."""
    arguments = _valid(tmp_path)
    monkeypatch.setattr("sys.argv", [str(Path(verifier.__file__)), *_argv(arguments)])
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(Path(verifier.__file__)), run_name="__main__")


@pytest.mark.parametrize(
    ("attribute", "value", "message"),
    [
        ("source_repository", "not-a-repository", "owner/name"),
        ("source_sha", "A" * 40, "lowercase 40-character"),
        ("workflow_run_id", "0", "workflow run ID"),
        ("evidence_artifact_id", "not-an-id", "artifact ID"),
        ("evidence_artifact_name", "bad/name", "artifact name"),
        ("evidence_artifact_digest", "sha256:nope", "artifact digest"),
        ("predicate_type", "https://example.invalid/predicate", "predicate type"),
        ("evidence_filename", "../evidence.json", "root-level filename"),
        ("evidence_filename", "bad\\name.json", "forbidden path"),
        ("profile_sha256", "0" * 63, "profile SHA-256"),
        ("profile_chronology_sha256", "A" * 64, "profile chronology SHA-256"),
        ("exact_head_receipt_sha256", "G" * 64, "exact-head receipt SHA-256"),
        ("exact_head_artifact_sha256", "4" * 63, "exact-head artifact SHA-256"),
        ("seed_manifest_sha256", "z" * 64, "seed manifest SHA-256"),
        ("recovery_evidence_sha256", "6" * 65, "recovery evidence SHA-256"),
        ("replication_provenance_sha256", "" , "replication provenance SHA-256"),
        ("evidence_sha256", "f" * 63, "evidence SHA-256"),
    ],
)
def test_malformed_external_control_plane_identity_fails_closed(
    tmp_path: Path, attribute: str, value: str, message: str
) -> None:
    """Reject malformed controls before their values can enter a predicate."""
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
    """A caller cannot replace bytes and simply provide their new outer digest."""
    arguments = _valid(tmp_path)
    document = _document()
    document[key] = value
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match=message):
        verifier.verify(arguments)


def test_document_type_confusion_fails_closed(tmp_path: Path) -> None:
    """Do not coerce strings, booleans, integers, arrays, or digest elements."""
    arguments = _valid(tmp_path)
    document = _document()
    document["profile_sha256"] = 1
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="profile_sha256 must be a JSON string"):
        verifier.verify(arguments)

    document = _document()
    document["workflow_run_id"] = True
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="workflow_run_id must be a JSON integer"):
        verifier.verify(arguments)

    document = _document()
    document["execution_artifact_sha256"] = "8" * 64
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="JSON array"):
        verifier.verify(arguments)

    document = _document()
    document["execution_artifact_sha256"] = [8, "9" * 64]
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="must be a JSON string"):
        verifier.verify(arguments)


def test_execution_artifact_order_cardinality_and_uniqueness_are_authoritative(
    tmp_path: Path,
) -> None:
    """Preserve repetition order and reject denominator or identity collapse."""
    arguments = _valid(tmp_path)
    document = _document()
    document["execution_artifact_sha256"] = list(reversed(EXECUTION))
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="ordered control evidence"):
        verifier.verify(arguments)

    document["execution_artifact_sha256"] = [EXECUTION[0], EXECUTION[0]]
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="distinct"):
        verifier.verify(arguments)

    document["execution_artifact_sha256"] = [EXECUTION[0]]
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="at least two replications"):
        verifier.verify(arguments)

    arguments = _valid(tmp_path / "control")
    arguments.execution_artifact_sha256 = [EXECUTION[0]]
    with pytest.raises(verifier.EvidenceError, match="at least two and distinct"):
        verifier.verify(arguments)


def test_execution_artifact_digest_syntax_is_validated_on_both_sides(tmp_path: Path) -> None:
    """Reject malformed represented and independently supplied execution identities."""
    arguments = _valid(tmp_path)
    document = _document()
    document["execution_artifact_sha256"] = ["x" * 64, EXECUTION[1]]
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="execution artifact SHA-256"):
        verifier.verify(arguments)

    arguments = _valid(tmp_path / "control")
    arguments.execution_artifact_sha256 = ["x" * 64, EXECUTION[1]]
    with pytest.raises(verifier.EvidenceError, match="execution artifact SHA-256"):
        verifier.verify(arguments)

    arguments = _valid(tmp_path / "duplicate")
    arguments.execution_artifact_sha256 = [EXECUTION[0], EXECUTION[0]]
    with pytest.raises(verifier.EvidenceError, match="at least two and distinct"):
        verifier.verify(arguments)


def test_sealed_directory_rejects_extra_missing_and_nonregular_members(tmp_path: Path) -> None:
    """Keep evidence cardinality exact and prevent symlink substitution."""
    arguments = _valid(tmp_path)
    root = Path(arguments.evidence_root)
    (root / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")
    with pytest.raises(verifier.EvidenceError, match="cardinality"):
        verifier.verify(arguments)

    (root / "unexpected.txt").unlink()
    evidence = root / arguments.evidence_filename
    evidence.unlink()
    with pytest.raises(verifier.EvidenceError, match="cardinality"):
        verifier.verify(arguments)

    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    evidence.symlink_to(outside)
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier.verify(arguments)


def test_root_path_must_exist_be_directories_and_reject_symlink_ancestry(tmp_path: Path) -> None:
    """Reject filesystem authority changes before reading sealed evidence."""
    arguments = _valid(tmp_path)
    arguments.evidence_root = str(tmp_path / "missing")
    with pytest.raises(verifier.EvidenceError, match="existing directory"):
        verifier.verify(arguments)

    ordinary_file = tmp_path / "not-a-directory"
    ordinary_file.write_text("x", encoding="utf-8")
    arguments.evidence_root = str(ordinary_file / "child")
    with pytest.raises(verifier.EvidenceError, match="existing directory"):
        verifier.verify(arguments)

    real = tmp_path / "real"
    real.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    arguments.evidence_root = str(alias)
    with pytest.raises(verifier.EvidenceError, match="reject symlinks"):
        verifier.verify(arguments)


def test_digest_mismatch_fails_even_when_document_is_otherwise_valid(tmp_path: Path) -> None:
    """Bind exact sealed bytes before parsing semantic content."""
    arguments = _valid(tmp_path)
    arguments.evidence_sha256 = "f" * 64
    with pytest.raises(verifier.EvidenceError, match="evidence SHA-256 mismatch"):
        verifier.verify(arguments)


def test_json_parser_is_strict_bounded_and_schema_closed(tmp_path: Path) -> None:
    """Reject duplicate keys, NaN, invalid UTF-8, nonobjects, and schema drift."""
    arguments = _valid(tmp_path)
    evidence = Path(arguments.evidence_root, arguments.evidence_filename)

    evidence.write_text('{"schema_version":"1.0","schema_version":"1.0"}\n', encoding="utf-8")
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())
    with pytest.raises(verifier.EvidenceError, match="duplicate JSON property"):
        verifier.verify(arguments)

    evidence.write_text('{"schema_version":NaN}\n', encoding="utf-8")
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())
    with pytest.raises(verifier.EvidenceError, match="non-finite JSON number"):
        verifier.verify(arguments)

    evidence.write_bytes(b"\xff")
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())
    with pytest.raises(verifier.EvidenceError, match="strict UTF-8"):
        verifier.verify(arguments)

    evidence.write_text("not-json\n", encoding="utf-8")
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())
    with pytest.raises(verifier.EvidenceError, match="invalid evidence JSON"):
        verifier.verify(arguments)

    _write_json(evidence, [1, 2, 3])
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())
    with pytest.raises(verifier.EvidenceError, match="root must be an object"):
        verifier.verify(arguments)

    document = _document()
    document["extra"] = "nope"
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="schema mismatch"):
        verifier.verify(arguments)

    document = _document()
    document.pop("seed_manifest_sha256")
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="schema mismatch"):
        verifier.verify(arguments)


def test_schema_version_and_evidence_size_are_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Version the input contract and enforce a hard evidence-size ceiling."""
    arguments = _valid(tmp_path)
    document = _document()
    document["schema_version"] = "2.0"
    _reseal(arguments, document)
    with pytest.raises(verifier.EvidenceError, match="schema_version must be 1.0"):
        verifier.verify(arguments)

    evidence = Path(arguments.evidence_root, arguments.evidence_filename)
    monkeypatch.setattr(verifier, "_MAX_EVIDENCE_BYTES", 1)
    arguments.evidence_sha256 = _sha256_bytes(evidence.read_bytes())
    with pytest.raises(verifier.EvidenceError, match="exceeds 1 bytes"):
        verifier.verify(arguments)


def test_output_symlink_is_rejected(tmp_path: Path) -> None:
    """Do not let verified output publication follow a caller-created symlink."""
    arguments = _valid(tmp_path)
    target = tmp_path / "target.json"
    target.write_text("{}\n", encoding="utf-8")
    output = Path(arguments.output_predicate)
    output.symlink_to(target)
    with pytest.raises(verifier.EvidenceError, match="output path must not be a symlink"):
        verifier.verify(arguments)


def test_atomic_writer_cleans_temporary_file_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Avoid stale trusted-looking temporary receipts after publication failure."""
    output = tmp_path / "out.json"

    def fail_replace(source: str, destination: str) -> None:
        assert Path(source).exists()
        assert Path(destination) == output
        raise OSError("replacement denied")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement denied"):
        verifier._atomic_json(output, {"a": 1})
    assert list(tmp_path.glob(".out.json.*")) == []
