"""Verification tests for normalized detector and independent verifier outputs."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from opencode_review_shadow_test_support import (
    candidate,
    digest_text,
    verifier_decision,
    verification_input,
    verify,
)


def test_supported_source_candidate_becomes_shadow_finding_without_publication() -> None:
    """A fully supported current-head candidate is retained only in shadow output."""
    report = verify.verify_bundle(verification_input())
    assert report["shadow_mode"] is True
    assert report["publication_enabled"] is False
    assert report["published_findings"] == []
    assert len(report["shadow_findings"]) == 1
    finding = report["shadow_findings"][0]
    assert finding["path"] == "src/example.py"
    assert finding["line"] == 12
    assert finding["detector_attempt_ids"] == ["detector_001"]
    assert finding["verifier_attempt_ids"] == ["verifier_001"]
    assert finding["finding_fingerprint"].startswith("sha256:")
    assert report["metrics"] == {
        "candidate_count": 1,
        "accepted_finding_count": 1,
        "rejected_candidate_count": 0,
        "duplicate_candidate_count": 0,
        "infrastructure_only_candidate_count": 0,
        "unsupported_candidate_count": 0,
        "source_contract_failure_count": 0,
        "insufficient_verifier_count": 0,
    }
    assert report["verification_sha256"].startswith("sha256:")


def test_infrastructure_only_candidate_is_rejected_without_source_authority() -> None:
    """Coverage or check commentary cannot enter the semantic shadow finding set."""
    value = verification_input(candidates=[candidate(infrastructure_only=True)])
    report = verify.verify_bundle(value)
    assert report["shadow_findings"] == []
    assert report["metrics"]["infrastructure_only_candidate_count"] == 1
    assert report["rejected_candidates"][0]["reason_code"] == "infrastructure_only"
    assert "path" not in report["rejected_candidates"][0]
    assert "line" not in report["rejected_candidates"][0]


def test_source_receipt_mismatch_is_rejected_not_silently_reanchored() -> None:
    """A candidate and verifier decision must match the trusted exact-line receipt."""
    wrong = digest_text("different line")
    value = verification_input(
        candidates=[candidate(source_line_sha256=wrong)],
        decisions=[verifier_decision(source_line_sha256=wrong)],
    )
    report = verify.verify_bundle(value)
    assert report["shadow_findings"] == []
    assert report["metrics"]["source_contract_failure_count"] == 1
    assert report["rejected_candidates"][0]["reason_code"] == "source_receipt_mismatch"


def test_rejected_or_missing_verifier_support_cannot_pass() -> None:
    """Detector prose alone is never a publishable or accepted shadow finding."""
    rejected = verify.verify_bundle(
        verification_input(decisions=[verifier_decision(outcome="rejected")])
    )
    assert rejected["shadow_findings"] == []
    assert rejected["metrics"]["unsupported_candidate_count"] == 1

    missing = verify.verify_bundle(verification_input(decisions=[]))
    assert missing["shadow_findings"] == []
    assert missing["metrics"]["insufficient_verifier_count"] == 1


def test_high_assurance_policy_requires_two_distinct_verifier_models() -> None:
    """Critical findings can require diverse independent verification rather than repetition."""
    value = verification_input(
        minimum_independent_verifiers=2,
        decisions=[
            verifier_decision(verifier_attempt_id="verifier_001"),
            verifier_decision(verifier_attempt_id="verifier_002"),
        ],
    )
    report = verify.verify_bundle(value)
    assert len(report["shadow_findings"]) == 1
    assert report["shadow_findings"][0]["verifier_attempt_ids"] == [
        "verifier_001",
        "verifier_002",
    ]

    same_model = copy.deepcopy(value)
    same_model["verifier_attempts"][1]["model_id"] = same_model["verifier_attempts"][0][
        "model_id"
    ]
    report = verify.verify_bundle(same_model)
    assert report["shadow_findings"] == []
    assert report["metrics"]["insufficient_verifier_count"] == 1


def test_detector_and_verifier_model_must_be_independent_when_policy_requires() -> None:
    """A model cannot verify its own finding under the diversity policy."""
    value = verification_input()
    value["verifier_attempts"][0]["model_id"] = value["detector_attempts"][0][
        "model_id"
    ]
    report = verify.verify_bundle(value)
    assert report["shadow_findings"] == []
    assert report["metrics"]["insufficient_verifier_count"] == 1


def test_duplicate_candidates_collapse_to_one_finding_with_all_receipts() -> None:
    """Equivalent detector findings are deduplicated by source and normalized root cause."""
    second = candidate(
        "candidate_002",
        detector_attempt_id="detector_002",
        root_cause="  The identity set   is not checked before aggregation. ",
    )
    value = verification_input(
        candidates=[candidate(), second],
        decisions=[
            verifier_decision("candidate_001"),
            verifier_decision("candidate_002"),
        ],
    )
    value["detector_attempts"].append(
        {
            **value["detector_attempts"][0],
            "attempt_id": "detector_002",
            "model_id": "mistralai/mistral-large-2-instruct",
            "output_sha256": digest_text("output:detector_002"),
        }
    )
    report = verify.verify_bundle(value)
    assert len(report["shadow_findings"]) == 1
    assert report["shadow_findings"][0]["detector_attempt_ids"] == [
        "detector_001",
        "detector_002",
    ]
    assert report["metrics"]["duplicate_candidate_count"] == 1


def test_failed_detector_or_verifier_attempt_cannot_supply_evidence() -> None:
    """Only completed exact-head attempts count toward detector or verifier evidence."""
    failed_detector = verification_input()
    failed_detector["detector_attempts"][0]["status"] = "failed"
    report = verify.verify_bundle(failed_detector)
    assert report["shadow_findings"] == []
    assert report["rejected_candidates"][0]["reason_code"] == "detector_not_complete"

    failed_verifier = verification_input()
    failed_verifier["verifier_attempts"][0]["status"] = "failed"
    report = verify.verify_bundle(failed_verifier)
    assert report["shadow_findings"] == []
    assert report["metrics"]["insufficient_verifier_count"] == 1


def test_equivalent_bundle_produces_deterministic_sorted_output() -> None:
    """Candidate order cannot change fingerprints, metrics, or output receipts."""
    c1 = candidate("candidate_b")
    c2 = candidate(
        "candidate_a",
        path="src/helper.py",
        line=4,
        source_line_sha256=digest_text("return identity"),
        root_cause="The helper returns an unsafe identity.",
    )
    d1 = verifier_decision("candidate_b")
    d2 = verifier_decision(
        "candidate_a", source_line_sha256=digest_text("return identity")
    )
    first = verify.verify_bundle(
        verification_input(candidates=[c1, c2], decisions=[d1, d2])
    )
    second = verify.verify_bundle(
        verification_input(candidates=[c2, c1], decisions=[d2, d1])
    )
    assert first == second
    assert [item["path"] for item in first["shadow_findings"]] == [
        "src/example.py",
        "src/helper.py",
    ]
