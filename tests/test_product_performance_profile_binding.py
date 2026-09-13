"""Contracts binding attested performance identity to sealed evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from scripts.ci import verify_product_performance_evidence as verifier

PREDICATE_TYPE = "https://contextualwisdomlab.org/attestations/product-performance/v1"
SOURCE_SHA = "a" * 40
ARTIFACT_DIGEST = "sha256:" + "b" * 64
WORKFLOW_PATH = Path(".github/workflows/product-performance-attestation.yml")


def _write_json(path: Path, value: object) -> str:
    """Write deterministic JSON and return its SHA-256 digest."""
    payload = json.dumps(value, sort_keys=True).encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _arguments(root: Path, tmp_path: Path) -> argparse.Namespace:
    """Create one otherwise-valid verifier request for first-commit evidence."""
    return argparse.Namespace(
        source_repository="ContextualWisdomLab/Orgmetra",
        source_sha=SOURCE_SHA,
        workflow_run_id="123456",
        evidence_artifact_id="789",
        evidence_artifact_name="orgmetra-performance-evidence",
        evidence_artifact_digest=ARTIFACT_DIGEST,
        evidence_root=str(root),
        result_filename="result.json",
        result_sha256=hashlib.sha256((root / "result.json").read_bytes()).hexdigest(),
        runtime_evidence_filename="runtime.json",
        runtime_evidence_sha256=hashlib.sha256((root / "runtime.json").read_bytes()).hexdigest(),
        fixture_filename="fixture.json",
        fixture_sha256=hashlib.sha256((root / "fixture.json").read_bytes()).hexdigest(),
        performance_profile="first_commit",
        predicate_type=PREDICATE_TYPE,
        output_predicate=str(tmp_path / "predicate.json"),
        output_manifest=str(tmp_path / "manifest.json"),
        require_selected_profile_binding=True,
    )


def _matching_evidence(root: Path) -> None:
    """Write one sealed evidence set matching the attested source and profile."""
    _write_json(
        root / "result.json",
        {"candidate_sha": SOURCE_SHA, "selected_profile": "first_commit"},
    )
    _write_json(
        root / "runtime.json",
        {"candidate_sha": SOURCE_SHA, "selected_profile": "first_commit"},
    )
    _write_json(root / "fixture.json", {"clearance": "right-cleared"})


def test_verify_accepts_matching_sealed_identity_binding(tmp_path: Path) -> None:
    """Preserve the positive path when sealed source and profile identity match."""
    root = tmp_path / "evidence"
    root.mkdir()
    _matching_evidence(root)
    arguments = _arguments(root, tmp_path)

    manifest = verifier.verify(arguments)

    assert manifest["verification_result"] == "VALID"
    assert manifest["source_sha"] == SOURCE_SHA
    assert manifest["performance_profile"] == "first_commit"


@pytest.mark.parametrize("member", ["result", "runtime"])
def test_verify_rejects_profile_not_bound_to_sealed_evidence(
    tmp_path: Path, member: str
) -> None:
    """Reject a caller profile that disagrees with either sealed profile declaration."""
    root = tmp_path / "evidence"
    root.mkdir()
    profiles = {"result": "first_commit", "runtime": "first_commit"}
    profiles[member] = "replay"
    _write_json(
        root / "result.json",
        {"candidate_sha": SOURCE_SHA, "selected_profile": profiles["result"]},
    )
    _write_json(
        root / "runtime.json",
        {"candidate_sha": SOURCE_SHA, "selected_profile": profiles["runtime"]},
    )
    _write_json(root / "fixture.json", {"clearance": "right-cleared"})
    arguments = _arguments(root, tmp_path)

    with pytest.raises(verifier.EvidenceError, match="selected_profile"):
        verifier.verify(arguments)


@pytest.mark.parametrize("member", ["result", "runtime"])
def test_verify_rejects_missing_sealed_profile_declaration(
    tmp_path: Path, member: str
) -> None:
    """Reject evidence that would otherwise leave the attested profile caller-controlled."""
    root = tmp_path / "evidence"
    root.mkdir()
    result = {"candidate_sha": SOURCE_SHA, "selected_profile": "first_commit"}
    runtime = {"candidate_sha": SOURCE_SHA, "selected_profile": "first_commit"}
    if member == "result":
        result.pop("selected_profile")
    else:
        runtime.pop("selected_profile")
    _write_json(root / "result.json", result)
    _write_json(root / "runtime.json", runtime)
    _write_json(root / "fixture.json", {"clearance": "right-cleared"})
    arguments = _arguments(root, tmp_path)

    with pytest.raises(verifier.EvidenceError, match="selected_profile"):
        verifier.verify(arguments)


@pytest.mark.parametrize("member", ["result", "runtime"])
def test_verify_rejects_source_sha_not_bound_to_sealed_evidence(
    tmp_path: Path, member: str
) -> None:
    """Reject a caller source SHA that disagrees with either sealed candidate SHA."""
    root = tmp_path / "evidence"
    root.mkdir()
    candidate_shas = {"result": SOURCE_SHA, "runtime": SOURCE_SHA}
    candidate_shas[member] = "c" * 40
    _write_json(
        root / "result.json",
        {"candidate_sha": candidate_shas["result"], "selected_profile": "first_commit"},
    )
    _write_json(
        root / "runtime.json",
        {"candidate_sha": candidate_shas["runtime"], "selected_profile": "first_commit"},
    )
    _write_json(root / "fixture.json", {"clearance": "right-cleared"})
    arguments = _arguments(root, tmp_path)

    with pytest.raises(verifier.EvidenceError, match="candidate_sha"):
        verifier.verify(arguments)


@pytest.mark.parametrize("member", ["result", "runtime"])
def test_verify_rejects_missing_sealed_source_sha_declaration(
    tmp_path: Path, member: str
) -> None:
    """Reject evidence that would leave attested source identity outside sealed data."""
    root = tmp_path / "evidence"
    root.mkdir()
    result = {"candidate_sha": SOURCE_SHA, "selected_profile": "first_commit"}
    runtime = {"candidate_sha": SOURCE_SHA, "selected_profile": "first_commit"}
    if member == "result":
        result.pop("candidate_sha")
    else:
        runtime.pop("candidate_sha")
    _write_json(root / "result.json", result)
    _write_json(root / "runtime.json", runtime)
    _write_json(root / "fixture.json", {"clearance": "right-cleared"})
    arguments = _arguments(root, tmp_path)

    with pytest.raises(verifier.EvidenceError, match="candidate_sha"):
        verifier.verify(arguments)


def test_central_workflow_requires_identity_binding_in_both_trust_jobs() -> None:
    """Require verifier and signer jobs to enable sealed commercial identity binding."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert workflow.count("--require-selected-profile-binding") == 2
