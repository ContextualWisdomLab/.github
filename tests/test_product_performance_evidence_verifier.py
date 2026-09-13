"""Unit contracts for inert product-performance evidence verification."""

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


def _digest(path: Path) -> str:
    """Return the SHA-256 digest of one fixture file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: object) -> None:
    """Write deterministic UTF-8 JSON for one test fixture."""
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _arguments(root: Path, tmp_path: Path) -> argparse.Namespace:
    """Create one valid verifier namespace for the three-file fixture."""
    result = root / "result.json"
    runtime = root / "runtime.json"
    fixture = root / "fixture.json"
    return argparse.Namespace(
        source_repository="ContextualWisdomLab/Orgmetra",
        source_sha=SOURCE_SHA,
        workflow_run_id="123456",
        evidence_artifact_id="789",
        evidence_artifact_name="orgmetra-performance-evidence",
        evidence_artifact_digest=ARTIFACT_DIGEST,
        evidence_root=str(root),
        result_filename=result.name,
        result_sha256=_digest(result),
        runtime_evidence_filename=runtime.name,
        runtime_evidence_sha256=_digest(runtime),
        fixture_filename=fixture.name,
        fixture_sha256=_digest(fixture),
        performance_profile="first_commit",
        predicate_type=PREDICATE_TYPE,
        output_predicate=str(tmp_path / "predicate.json"),
        output_manifest=str(tmp_path / "manifest.json"),
    )


def _cli(arguments: argparse.Namespace) -> list[str]:
    """Serialize one valid namespace into the verifier's public CLI contract."""
    return [
        "--source-repository",
        arguments.source_repository,
        "--source-sha",
        arguments.source_sha,
        "--workflow-run-id",
        arguments.workflow_run_id,
        "--evidence-artifact-id",
        arguments.evidence_artifact_id,
        "--evidence-artifact-name",
        arguments.evidence_artifact_name,
        "--evidence-artifact-digest",
        arguments.evidence_artifact_digest,
        "--evidence-root",
        arguments.evidence_root,
        "--result-filename",
        arguments.result_filename,
        "--result-sha256",
        arguments.result_sha256,
        "--runtime-evidence-filename",
        arguments.runtime_evidence_filename,
        "--runtime-evidence-sha256",
        arguments.runtime_evidence_sha256,
        "--fixture-filename",
        arguments.fixture_filename,
        "--fixture-sha256",
        arguments.fixture_sha256,
        "--performance-profile",
        arguments.performance_profile,
        "--predicate-type",
        arguments.predicate_type,
        "--output-predicate",
        arguments.output_predicate,
        "--output-manifest",
        arguments.output_manifest,
    ]


@pytest.fixture
def evidence(tmp_path: Path) -> tuple[Path, argparse.Namespace]:
    """Create a valid three-file inert evidence set and verifier arguments."""
    root = tmp_path / "evidence"
    root.mkdir()
    _write_json(root / "result.json", {"metrics": {"p95_ms": 12.3}})
    _write_json(root / "runtime.json", {"runner": "k6", "cpu": "observed"})
    _write_json(root / "fixture.json", {"clearance": "right-cleared", "records": [1]})
    return root, _arguments(root, tmp_path)


def test_verify_binds_exact_three_file_evidence(evidence: tuple[Path, argparse.Namespace]) -> None:
    """Emit deterministic manifest and predicate bound to the exact evidence bytes."""
    root, arguments = evidence

    manifest = verifier.verify(arguments)
    predicate = json.loads(Path(arguments.output_predicate).read_text(encoding="utf-8"))

    assert manifest["result"] == "PASS"
    assert manifest["source_repository"] == arguments.source_repository
    assert manifest["source_sha"] == SOURCE_SHA
    assert manifest["performance_profile"] == "first_commit"
    assert [item["filename"] for item in manifest["files"]] == [
        "fixture.json",
        "result.json",
        "runtime.json",
    ]
    assert predicate == {
        "attestation_claim": "origin_and_integrity_only",
        "does_not_prove": [
            "latency_threshold_passed",
            "production_equivalence",
            "fixture_scientific_validity",
            "fixture_right_clearance",
        ],
        "evidence": {
            "artifact_digest": ARTIFACT_DIGEST,
            "artifact_id": "789",
            "artifact_name": "orgmetra-performance-evidence",
            "fixture": {"filename": "fixture.json", "sha256": _digest(root / "fixture.json")},
            "result": {"filename": "result.json", "sha256": _digest(root / "result.json")},
            "runtime": {"filename": "runtime.json", "sha256": _digest(root / "runtime.json")},
        },
        "performance_profile": "first_commit",
        "predicate_type": PREDICATE_TYPE,
        "schema_version": "1.0",
        "source_repository": "ContextualWisdomLab/Orgmetra",
        "source_sha": SOURCE_SHA,
        "workflow_run_id": "123456",
    }
    assert json.loads(Path(arguments.output_manifest).read_text(encoding="utf-8")) == manifest


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_repository", "bad repo", "source repository"),
        ("source_sha", "A" * 40, "source SHA"),
        ("workflow_run_id", "0", "workflow run ID"),
        ("evidence_artifact_id", "abc", "artifact ID"),
        ("evidence_artifact_name", "", "artifact name"),
        ("evidence_artifact_digest", "b" * 64, "artifact digest"),
        ("performance_profile", "UPPER", "performance profile"),
        ("predicate_type", "https://example.invalid/v1", "predicate type"),
        ("result_filename", "../result.json", "result filename"),
        ("runtime_evidence_filename", "runtime\\evil.json", "runtime evidence filename"),
        ("fixture_filename", "..", "fixture filename"),
        ("result_sha256", "A" * 64, "result SHA-256"),
        ("runtime_evidence_sha256", "x" * 64, "runtime evidence SHA-256"),
        ("fixture_sha256", "1", "fixture SHA-256"),
    ],
)
def test_verify_rejects_invalid_control_fields(
    evidence: tuple[Path, argparse.Namespace], field: str, value: str, message: str
) -> None:
    """Reject malformed control-plane identities before publishing a receipt."""
    _, arguments = evidence
    setattr(arguments, field, value)

    with pytest.raises(verifier.EvidenceError, match=message):
        verifier.verify(arguments)


def test_require_regular_file_rejects_missing_and_directory(tmp_path: Path) -> None:
    """Reject absent or directory members at the byte-reading boundary."""
    missing = tmp_path / "missing.json"
    with pytest.raises(verifier.EvidenceError, match="missing evidence file"):
        verifier._require_regular_file(missing)

    directory = tmp_path / "directory.json"
    directory.mkdir()
    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier._require_regular_file(directory)


def test_verify_rejects_duplicate_filenames(evidence: tuple[Path, argparse.Namespace]) -> None:
    """Require result, runtime, and fixture to remain three distinct members."""
    _, arguments = evidence
    arguments.fixture_filename = arguments.result_filename
    arguments.fixture_sha256 = arguments.result_sha256

    with pytest.raises(verifier.EvidenceError, match="distinct"):
        verifier.verify(arguments)


def test_verify_rejects_missing_and_extra_members(evidence: tuple[Path, argparse.Namespace]) -> None:
    """Fail closed when the artifact cardinality differs from the three-file contract."""
    root, arguments = evidence
    (root / "extra.json").write_text("{}", encoding="utf-8")

    with pytest.raises(verifier.EvidenceError, match="cardinality mismatch"):
        verifier.verify(arguments)

    (root / "extra.json").unlink()
    (root / "runtime.json").unlink()
    with pytest.raises(verifier.EvidenceError, match="cardinality mismatch"):
        verifier.verify(arguments)


def test_verify_rejects_non_regular_directory_member(evidence: tuple[Path, argparse.Namespace]) -> None:
    """Reject nested directories rather than treating them as ignorable artifact members."""
    root, arguments = evidence
    (root / "nested").mkdir()

    with pytest.raises(verifier.EvidenceError, match="unexpected non-regular"):
        verifier.verify(arguments)


def test_verify_rejects_symlink_member(evidence: tuple[Path, argparse.Namespace]) -> None:
    """Do not follow an evidence-member symlink even when its target is regular."""
    root, arguments = evidence
    target = root / "runtime-target.json"
    (root / "runtime.json").rename(target)
    (root / "runtime.json").symlink_to(target.name)

    with pytest.raises(verifier.EvidenceError, match="non-regular"):
        verifier.verify(arguments)


def test_verify_rejects_symlinked_root_ancestor(tmp_path: Path) -> None:
    """Reject evidence roots reached through a symbolic-link ancestor."""
    real_parent = tmp_path / "real"
    root = real_parent / "evidence"
    root.mkdir(parents=True)
    _write_json(root / "result.json", {})
    _write_json(root / "runtime.json", {})
    _write_json(root / "fixture.json", {})
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    arguments = _arguments(linked_parent / "evidence", tmp_path)

    with pytest.raises(verifier.EvidenceError, match="ancestor"):
        verifier.verify(arguments)


def test_validate_evidence_root_rejects_non_directory_ancestor(tmp_path: Path) -> None:
    """Convert a path-through-file failure into the stable fail-closed domain error."""
    blocking = tmp_path / "blocking"
    blocking.write_text("not a directory", encoding="utf-8")

    with pytest.raises(verifier.EvidenceError, match="directories"):
        verifier._validate_evidence_root(blocking / "evidence")


def test_verify_rejects_digest_mismatch(evidence: tuple[Path, argparse.Namespace]) -> None:
    """Reject replacement bytes even when the filename remains unchanged."""
    root, arguments = evidence
    _write_json(root / "result.json", {"substituted": True})

    with pytest.raises(verifier.EvidenceError, match="digest mismatch"):
        verifier.verify(arguments)


@pytest.mark.parametrize(
    ("filename", "payload", "message"),
    [
        ("result.json", b'{"a":1,"a":2}', "duplicate JSON property"),
        ("runtime.json", b'{"x":NaN}', "non-finite JSON number"),
        ("fixture.json", b"\x80", "invalid UTF-8"),
        ("result.json", b"[]", "JSON object"),
        ("runtime.json", b"{", "invalid JSON"),
    ],
)
def test_verify_rejects_malformed_json_members(
    evidence: tuple[Path, argparse.Namespace], filename: str, payload: bytes, message: str
) -> None:
    """Reject malformed or non-object JSON even when its external digest is updated."""
    root, arguments = evidence
    path = root / filename
    path.write_bytes(payload)
    digest = _digest(path)
    if filename == "result.json":
        arguments.result_sha256 = digest
    elif filename == "runtime.json":
        arguments.runtime_evidence_sha256 = digest
    else:
        arguments.fixture_sha256 = digest

    with pytest.raises(verifier.EvidenceError, match=message):
        verifier.verify(arguments)


def test_verify_rejects_oversized_json_member(
    evidence: tuple[Path, argparse.Namespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bound inert JSON evidence without changing the commercial sample semantics."""
    root, arguments = evidence
    monkeypatch.setattr(verifier, "_MAX_RESULT_BYTES", 1)

    with pytest.raises(verifier.EvidenceError, match="exceeds"):
        verifier.verify(arguments)


def test_verify_rejects_non_directory_root(tmp_path: Path) -> None:
    """Reject a missing or non-directory evidence root before member traversal."""
    root = tmp_path / "not-directory"
    root.write_text("x", encoding="utf-8")

    with pytest.raises(verifier.EvidenceError, match="directories"):
        verifier._validate_evidence_root(root)
    root.unlink()
    with pytest.raises(verifier.EvidenceError, match="existing"):
        verifier._validate_evidence_root(root)


def test_atomic_json_rejects_output_symlink(tmp_path: Path) -> None:
    """Do not replace an output selected through a symbolic-link endpoint."""
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    output = tmp_path / "output.json"
    output.symlink_to(target.name)

    with pytest.raises(verifier.EvidenceError, match="must not be a symlink"):
        verifier._atomic_json(output, {"x": 1})


def test_atomic_json_cleans_temporary_when_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove the temporary sibling when atomic replacement itself fails."""
    output = tmp_path / "output.json"

    def fail_replace(source: str, destination: Path) -> None:
        """Simulate a filesystem failure after the temporary file is written."""
        del source, destination
        raise OSError("replace failed")

    monkeypatch.setattr(verifier.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        verifier._atomic_json(output, {"x": 1})
    assert list(tmp_path.glob(".output.json.*")) == []


def test_atomic_json_cleans_temporary_after_replace(tmp_path: Path) -> None:
    """Publish deterministically and leave no temporary sibling behind."""
    output = tmp_path / "nested" / "output.json"
    verifier._atomic_json(output, {"z": 1})

    assert output.read_text(encoding="utf-8") == '{"z":1}\n'
    assert list(output.parent.glob(".output.json.*")) == []


def test_parser_accepts_the_complete_public_contract(
    evidence: tuple[Path, argparse.Namespace]
) -> None:
    """Keep every workflow-supplied CLI argument wired to the verifier parser."""
    _, arguments = evidence

    parsed = verifier._parser().parse_args(_cli(arguments))

    assert vars(parsed) == vars(arguments)


def test_main_returns_zero_for_valid_evidence(
    evidence: tuple[Path, argparse.Namespace], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Expose successful verification through the production CLI entry point."""
    _, arguments = evidence
    parser = type("P", (), {"parse_args": lambda self: arguments})()
    monkeypatch.setattr(verifier, "_parser", lambda: parser)

    assert verifier.main() == 0


def test_main_reports_evidence_error_without_traceback(
    evidence: tuple[Path, argparse.Namespace], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Expose deterministic validation failure as a concise CLI error."""
    _, arguments = evidence
    arguments.source_sha = "bad"
    parser = type("P", (), {"parse_args": lambda self: arguments})()
    monkeypatch.setattr(verifier, "_parser", lambda: parser)

    assert verifier.main() == 2
    assert "source SHA" in capsys.readouterr().err
