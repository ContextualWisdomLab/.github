"""Behavior tests for independent semantic and merge-readiness channels."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from opencode_review_decision_test_support import check, decision, envelope, finding


def test_coverage_failure_cannot_create_a_source_finding() -> None:
    """Coverage failure must block readiness without becoming a line-level defect."""
    report = decision.build_decision(envelope(coverage_state="failure"))
    assert report["review_verdict"] == "APPROVE"
    assert report["merge_readiness"] == "BLOCKED"
    assert report["findings"] == []
    assert report["semantic_status"] == "complete"
    assert report["infrastructure_blockers"] == [
        {
            "blocker_code": "coverage_not_successful",
            "evidence_name": "coverage",
            "state": "failure",
            "check_name": None,
        }
    ]
    assert all(
        "path" not in blocker and "line" not in blocker
        for blocker in report["infrastructure_blockers"]
    )


def test_semantic_finding_survives_independent_coverage_failure() -> None:
    """A real source defect and infrastructure blocker remain separate channels."""
    report = decision.build_decision(
        envelope(findings=[finding()], coverage_state="failure")
    )
    assert report["review_verdict"] == "REQUEST_CHANGES"
    assert report["merge_readiness"] == "BLOCKED"
    assert [item["finding_id"] for item in report["findings"]] == ["finding_001"]
    assert report["infrastructure_blockers"][0]["evidence_name"] == "coverage"


def test_semantic_verdict_matrix_is_independent_of_merge_evidence() -> None:
    """Complete semantic review alone chooses approve, comment, or request changes."""
    assert decision.build_decision(envelope())["review_verdict"] == "APPROVE"
    assert (
        decision.build_decision(envelope(findings=[finding(blocking=False)]))[
            "review_verdict"
        ]
        == "COMMENT"
    )
    assert (
        decision.build_decision(envelope(findings=[finding(blocking=True)]))[
            "review_verdict"
        ]
        == "REQUEST_CHANGES"
    )
    for status in ("unavailable", "failed"):
        report = decision.build_decision(envelope(semantic_status=status))
        assert report["review_verdict"] == "ABSTAIN"
        assert report["findings"] == []


def test_merge_readiness_ready_blocked_and_unknown_states() -> None:
    """Readiness distinguishes hard failure from latency or absent evidence."""
    assert decision.build_decision(envelope())["merge_readiness"] == "READY"
    assert (
        decision.build_decision(envelope(findings=[finding()]))["merge_readiness"]
        == "BLOCKED"
    )
    assert (
        decision.build_decision(envelope(checks=[check(state="cancelled")]))[
            "merge_readiness"
        ]
        == "BLOCKED"
    )
    for state in ("pending", "queued", "absent"):
        assert (
            decision.build_decision(envelope(checks=[check(state=state)]))[
                "merge_readiness"
            ]
            == "UNKNOWN"
        )
    assert (
        decision.build_decision(envelope(semantic_status="unavailable"))[
            "merge_readiness"
        ]
        == "UNKNOWN"
    )


def test_required_and_advisory_checks_are_classified_separately() -> None:
    """Only required checks block readiness, while advisory evidence is recorded."""
    report = decision.build_decision(
        envelope(
            checks=[
                check("required-ci", state="success", required=True),
                check("advisory-lint", state="failure", required=False),
            ]
        )
    )
    assert report["merge_readiness"] == "READY"
    assert report["infrastructure_blockers"] == []
    manifest = report["evidence_manifest"]
    assert manifest["required_check_count"] == 1
    assert manifest["successful_required_check_count"] == 1
    assert manifest["advisory_check_count"] == 1


def test_every_non_successful_policy_surface_produces_non_source_blockers() -> None:
    """Coverage, approval, protection, and required checks report stable blockers."""
    report = decision.build_decision(
        envelope(
            coverage_state="neutral",
            approval_state="absent",
            protection_state="pending",
            checks=[check("unit", state="failure"), check("security", state="skipped")],
        )
    )
    assert report["merge_readiness"] == "BLOCKED"
    assert {
        (item["evidence_name"], item["state"], item["check_name"])
        for item in report["infrastructure_blockers"]
    } == {
        ("coverage", "neutral", None),
        ("independent_approval", "absent", None),
        ("branch_protection", "pending", None),
        ("required_check", "failure", "unit"),
        ("required_check", "skipped", "security"),
    }
    assert all(
        "path" not in item and "line" not in item
        for item in report["infrastructure_blockers"]
    )


def test_output_is_deterministic_and_receipt_bound() -> None:
    """Equivalent exact-head input produces one stable content-addressed decision."""
    value = envelope(findings=[finding(blocking=False)])
    first = decision.build_decision(copy.deepcopy(value))
    second = decision.build_decision(copy.deepcopy(value))
    assert first == second
    assert first["decision_sha256"].startswith("sha256:")
    assert first["evidence_manifest"]["input_sha256"].startswith("sha256:")
