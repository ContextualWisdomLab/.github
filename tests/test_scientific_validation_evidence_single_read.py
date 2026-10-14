"""Hostile contracts for one-read evidence identity and atomic output refusal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
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
        evidence_artifact_size_in_bytes="556",
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

    assert swapped is False
    assert not Path(arguments.output_predicate).exists()
    assert not Path(arguments.output_manifest).exists()


def test_pinned_root_descriptor_prevents_ancestor_path_swap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep evidence selection on the directory inode validated before a pathname replacement."""
    root = tmp_path / "sealed"
    root.mkdir()
    evidence_name = "scientific-validation-evidence.json"
    trusted_bytes = (
        json.dumps(_document(), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    (root / evidence_name).write_bytes(trusted_bytes)

    replacement = tmp_path / "replacement"
    replacement.mkdir()
    replacement_bytes = b" " + trusted_bytes
    (replacement / evidence_name).write_bytes(replacement_bytes)
    arguments = _arguments(tmp_path, _sha256_bytes(replacement_bytes))

    original_reader = verifier._read_evidence_once
    swapped = False

    def swap_root_then_read(path: Path | str, *args: object, **kwargs: object) -> bytes:
        nonlocal swapped
        if not swapped:
            swapped = True
            root.rename(tmp_path / "sealed-original")
            root.symlink_to(replacement, target_is_directory=True)
        return original_reader(path, *args, **kwargs)

    monkeypatch.setattr(verifier, "_read_evidence_once", swap_root_then_read)
    with pytest.raises(verifier.EvidenceError, match="evidence SHA-256 mismatch"):
        verifier.verify(arguments)

    assert swapped is True
    assert not Path(arguments.output_predicate).exists()
    assert not Path(arguments.output_manifest).exists()


def test_directory_descriptor_walk_rejects_symlink_component(tmp_path: Path) -> None:
    """Reject a symlinked root component while acquiring the pinned directory descriptor."""
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(verifier.EvidenceError, match="existing unsymlinked directories"):
        verifier._open_directory_without_symlinks(alias)


def test_descriptor_reader_requests_nonblocking_untrusted_leaf_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Require nonblocking open before the untrusted member's file type is known."""
    evidence = tmp_path / "ordinary.json"
    evidence.write_text("{}\n", encoding="utf-8")
    original_open = os.open
    observed_flags = 0

    def capture_open(path: os.PathLike[str] | str, flags: int, *args: object, **kwargs: object) -> int:
        nonlocal observed_flags
        observed_flags = flags
        assert flags & os.O_NOFOLLOW
        assert flags & os.O_NONBLOCK
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(verifier.os, "open", capture_open)
    assert verifier._read_evidence_once(evidence) == b"{}\n"
    assert observed_flags & os.O_NONBLOCK


def test_descriptor_reader_normalizes_post_open_read_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep post-open sealed-evidence I/O faults inside the typed rejection boundary."""
    evidence = tmp_path / "ordinary.json"
    evidence.write_text("{}\n", encoding="utf-8")

    class FaultingStream:
        def __enter__(self) -> FaultingStream:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _: int) -> bytes:
            raise OSError("synthetic sealed-evidence read failure")

    monkeypatch.setattr(verifier.os, "fdopen", lambda *_args, **_kwargs: FaultingStream())
    with pytest.raises(verifier.EvidenceError, match="evidence read failed"):
        verifier._read_evidence_once(evidence)


def test_descriptor_reader_and_legacy_regular_file_guard_fail_closed(tmp_path: Path) -> None:
    """Exercise symlink, directory, missing, and ordinary-file boundary outcomes directly."""
    ordinary = tmp_path / "ordinary.json"
    ordinary.write_text("{}\n", encoding="utf-8")
    verifier._require_regular_file(ordinary)

    missing = tmp_path / "missing.json"
    with pytest.raises(verifier.EvidenceError, match="missing evidence file"):
        verifier._require_regular_file(missing)

    symlink = tmp_path / "alias.json"
    symlink.symlink_to(ordinary)
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier._require_regular_file(symlink)
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier._read_evidence_once(symlink)

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier._read_evidence_once(directory)


def test_atomic_writer_rejects_symlink_leaf_without_mutating_target(tmp_path: Path) -> None:
    """Exercise the atomic writer's own leaf-symlink guard, not an earlier verifier guard."""
    target = tmp_path / "target.json"
    target.write_text("original\n", encoding="utf-8")
    output = tmp_path / "output.json"
    output.symlink_to(target)

    with pytest.raises(verifier.EvidenceError, match="output path must not be a symbolic link"):
        verifier._atomic_json(output, {"replacement": True})

    assert target.read_text(encoding="utf-8") == "original\n"


def test_strict_json_loader_normalizes_integer_conversion_limit() -> None:
    """Keep Python integer-conversion limits inside the typed evidence rejection contract."""
    raw = ("{\"workflow_run_id\":" + ("9" * 5000) + "}").encode("utf-8")

    with pytest.raises(verifier.EvidenceError, match="JSON parser resource limit"):
        verifier._load_strict_json_object(raw, "evidence JSON")


def test_strict_json_loader_normalizes_excessive_nesting() -> None:
    """Keep parser recursion exhaustion inside the typed evidence rejection contract."""
    raw = (("[" * 10000) + "0" + ("]" * 10000)).encode("utf-8")

    with pytest.raises(verifier.EvidenceError, match="JSON parser resource limit"):
        verifier._load_strict_json_object(raw, "evidence JSON")
