"""Filesystem-authority contracts for scientific-validation verifier outputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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


def test_output_parent_swap_cannot_redirect_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep publication bound to the validated output directory inode after a pathname swap."""
    arguments = _arguments(tmp_path)
    output_parent = tmp_path / "published"
    pinned_parent = tmp_path / "published-pinned"
    redirected_parent = tmp_path / "redirected"
    output_parent.mkdir()
    redirected_parent.mkdir()
    arguments.output_predicate = str(output_parent / "predicate.json")
    arguments.output_manifest = str(output_parent / "manifest.json")

    original_validate = verifier._validate_output_path
    validation_count = 0

    def validate_then_swap(path: Path, sealed_root: Path):  # type: ignore[no-untyped-def]
        nonlocal validation_count
        target = original_validate(path, sealed_root)
        validation_count += 1
        if validation_count == 2:
            output_parent.rename(pinned_parent)
            output_parent.symlink_to(redirected_parent, target_is_directory=True)
        return target

    monkeypatch.setattr(verifier, "_validate_output_path", validate_then_swap)

    verifier.verify(arguments)

    assert (pinned_parent / "predicate.json").is_file()
    assert (pinned_parent / "manifest.json").is_file()
    assert list(redirected_parent.iterdir()) == []


def test_preexisting_regular_output_is_not_replaced(tmp_path: Path) -> None:
    """Refuse stale verifier output instead of relabeling it as a fresh receipt."""
    arguments = _arguments(tmp_path)
    predicate = Path(arguments.output_predicate)
    predicate.write_text("stale-predicate\n", encoding="utf-8")

    with pytest.raises(verifier.EvidenceError, match="output leaf must not already exist"):
        verifier.verify(arguments)

    assert predicate.read_text(encoding="utf-8") == "stale-predicate\n"
    assert not Path(arguments.output_manifest).exists()


def test_nonreplaceable_manifest_is_rejected_before_predicate_publication(tmp_path: Path) -> None:
    """Preflight both receipt leaves so a bad manifest target cannot leave a lone predicate."""
    arguments = _arguments(tmp_path)
    manifest = Path(arguments.output_manifest)
    manifest.mkdir()

    with pytest.raises(verifier.EvidenceError, match="output leaf must not already exist"):
        verifier.verify(arguments)

    assert not Path(arguments.output_predicate).exists()
    assert manifest.is_dir()


def test_atomic_writer_does_not_clobber_existing_regular_leaf(tmp_path: Path) -> None:
    """Keep the final publication primitive no-clobber even after verifier preflight."""
    output = tmp_path / "receipt.json"
    output.write_text("existing\n", encoding="utf-8")

    with pytest.raises(verifier.EvidenceError, match="output leaf must not already exist"):
        verifier._atomic_json(output, {"replacement": True})

    assert output.read_text(encoding="utf-8") == "existing\n"


def test_atomic_writer_fails_closed_when_leaf_appears_during_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Use a no-clobber final primitive when a leaf appears after the first absence check."""
    output = tmp_path / "receipt.json"
    original_link = os.link
    collided = False

    def collide_then_link(src: str, dst: str, *args: object, **kwargs: object) -> None:
        nonlocal collided
        if not collided:
            collided = True
            output.write_text("raced\n", encoding="utf-8")
        original_link(src, dst, *args, **kwargs)

    monkeypatch.setattr(verifier.os, "link", collide_then_link)

    with pytest.raises(verifier.EvidenceError, match="output leaf must not already exist"):
        verifier._atomic_json(output, {"replacement": True})

    assert collided is True
    assert output.read_text(encoding="utf-8") == "raced\n"


def test_atomic_writer_normalizes_final_publication_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Return a typed verifier rejection instead of leaking a raw publication OSError."""
    output = tmp_path / "receipt.json"

    def deny_link(*args: object, **kwargs: object) -> None:
        raise PermissionError("simulated publication denial")

    monkeypatch.setattr(verifier.os, "link", deny_link)

    with pytest.raises(verifier.EvidenceError, match="output publication failed"):
        verifier._atomic_json(output, {"replacement": True})

    assert not output.exists()


def test_manifest_commits_exact_published_predicate_bytes(tmp_path: Path) -> None:
    """Treat the final manifest as a commit marker for the exact predicate bytes."""
    arguments = _arguments(tmp_path)

    verifier.verify(arguments)

    predicate_bytes = Path(arguments.output_predicate).read_bytes()
    manifest = json.loads(Path(arguments.output_manifest).read_text(encoding="utf-8"))
    assert manifest["predicate_sha256"] == hashlib.sha256(predicate_bytes).hexdigest()


def test_manifest_race_leaves_no_completed_receipt_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lone predicate is inert when manifest publication loses a no-clobber race."""
    arguments = _arguments(tmp_path)
    predicate = Path(arguments.output_predicate)
    manifest = Path(arguments.output_manifest)
    original_publish = verifier._atomic_json_at
    publish_count = 0

    def publish_then_race(parent_descriptor: int, filename: str, value: dict[str, object]):
        nonlocal publish_count
        publish_count += 1
        result = original_publish(parent_descriptor, filename, value)
        if publish_count == 1:
            manifest.write_text("raced-manifest\n", encoding="utf-8")
        return result

    monkeypatch.setattr(verifier, "_atomic_json_at", publish_then_race)

    with pytest.raises(verifier.EvidenceError, match="output leaf must not already exist"):
        verifier.verify(arguments)

    assert publish_count == 2
    assert predicate.is_file()
    assert manifest.read_text(encoding="utf-8") == "raced-manifest\n"


def test_manifest_is_self_describing_and_versioned(tmp_path: Path) -> None:
    """Give the signer handoff an explicit major-versioned contract identity."""
    arguments = _arguments(tmp_path)

    verifier.verify(arguments)

    manifest = json.loads(Path(arguments.output_manifest).read_text(encoding="utf-8"))
    assert manifest["manifest_type"] == (
        "https://contextualwisdomlab.org/attestations/scientific-validation-manifest/v1"
    )
    assert manifest["schema_version"] == "1.0"


def test_receipt_manifest_validator_rejects_unversioned_or_tampered_completion_marker(
    tmp_path: Path,
) -> None:
    """Fail closed when a signer sees an ambiguous manifest or altered predicate bytes."""
    arguments = _arguments(tmp_path)
    manifest = verifier.verify(arguments)
    predicate_bytes = Path(arguments.output_predicate).read_bytes()
    manifest_bytes = Path(arguments.output_manifest).read_bytes()

    assert verifier.validate_receipt_manifest(manifest_bytes, predicate_bytes) == manifest

    unversioned = dict(manifest)
    unversioned.pop("manifest_type")
    with pytest.raises(verifier.EvidenceError, match="receipt manifest schema mismatch"):
        verifier.validate_receipt_manifest(verifier._canonical_json_bytes(unversioned), predicate_bytes)

    with pytest.raises(verifier.EvidenceError, match="predicate SHA-256"):
        verifier.validate_receipt_manifest(manifest_bytes, predicate_bytes + b"tampered")
