"""Regression tests for independent exact-artifact SBOM review findings."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from scripts.ci import verify_exact_artifact_sbom_handoff as verifier

ROOT = Path(__file__).resolve().parents[1]
ATTESTATION_WORKFLOW = ROOT / ".github" / "workflows" / "exact-artifact-sbom-attestation.yml"


def test_evidence_root_rejects_symlinked_ancestor(tmp_path: Path) -> None:
    """A symlinked ancestor must not relocate the declared sealed-evidence root."""

    real_parent = tmp_path / "real-parent"
    evidence_root = real_parent / "sealed-evidence"
    evidence_root.mkdir(parents=True)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    arguments = argparse.Namespace(
        source_repository="ContextualWisdomLab/example",
        source_sha="a" * 40,
        evidence_artifact_digest="sha256:" + ("b" * 64),
        evidence_root=str(linked_parent / "sealed-evidence"),
        wheel_filename="example.whl",
        wheel_sbom_filename="example-wheel.cdx.json",
        sdist_filename="example.tar.gz",
        sdist_sbom_filename="example-sdist.cdx.json",
        predicate_type="https://cyclonedx.org/bom",
    )

    with pytest.raises(verifier.EvidenceError, match="evidence root"):
        verifier.verify(arguments)


def test_offline_readme_embeds_copyable_exact_verification_commands() -> None:
    """The exported README must contain exact online and offline verification commands."""

    workflow = ATTESTATION_WORKFLOW.read_text(encoding="utf-8")
    start = workflow.index("cat > offline-attestation-evidence/README.md")
    end_marker = "} >> offline-attestation-evidence/README.md"
    readme_block = workflow[start : workflow.index(end_marker, start) + len(end_marker)]

    required = (
        "## Online verification commands",
        "## Offline verification commands",
        'gh attestation verify "sealed-evidence/${WHEEL_FILENAME}"',
        'gh attestation verify "sealed-evidence/${SDIST_FILENAME}"',
        '--bundle offline-attestation-evidence/wheel-sbom-attestation.json',
        '--bundle offline-attestation-evidence/sdist-sbom-attestation.json',
        '--custom-trusted-root offline-attestation-evidence/trusted_root.jsonl',
        '--repo "$SOURCE_REPOSITORY"',
        '--signer-repo "$SIGNER_REPOSITORY"',
        '--signer-workflow "$signer_workflow"',
        '--source-digest "$SOURCE_SHA"',
        '--predicate-type "$PREDICATE_TYPE"',
    )
    for fragment in required:
        assert fragment in readme_block
