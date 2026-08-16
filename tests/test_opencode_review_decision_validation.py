"""Validation tests for exact-head OpenCode decision evidence."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from opencode_review_decision_test_support import check, decision, envelope, finding


def test_exact_head_binding_rejects_stale_semantic_and_merge_evidence() -> None:
    """No semantic, check, or policy evidence may transfer from another head."""
    stale_semantic = envelope()
    stale_semantic["semantic_review"]["reviewed_head_sha"] = "c" * 40
    with pytest.raises(decision.DecisionValidationError, match="reviewed_head_sha"):
        decision.build_decision(stale_semantic)

    stale_merge = envelope()
    stale_merge["merge_evidence"]["evidence_head_sha"] = "c" * 40
    with pytest.raises(decision.DecisionValidationError, match="evidence_head_sha"):
        decision.build_decision(stale_merge)

    stale_check = envelope()
    stale_check["merge_evidence"]["required_checks"][0]["head_sha"] = "c" * 40
    with pytest.raises(
        decision.DecisionValidationError, match=r"required_checks\[0\].head_sha"
    ):
        decision.build_decision(stale_check)


def test_incomplete_semantic_review_cannot_carry_findings_or_head_claim() -> None:
    """Unavailable or failed reviews abstain without synthetic source evidence."""
    for status in ("unavailable", "failed"):
        with_findings = envelope(semantic_status=status, findings=[finding()])
        with pytest.raises(
            decision.DecisionValidationError, match="must not contain findings"
        ):
            decision.build_decision(with_findings)

        with_head = envelope(semantic_status=status)
        with_head["semantic_review"]["reviewed_head_sha"] = "b" * 40
        with pytest.raises(decision.DecisionValidationError, match="must be null"):
            decision.build_decision(with_head)


def test_complete_semantic_review_requires_exact_head() -> None:
    """A completed semantic verdict without an exact reviewed head is invalid."""
    value = envelope()
    value["semantic_review"]["reviewed_head_sha"] = None
    with pytest.raises(decision.DecisionValidationError, match="reviewed_head_sha"):
        decision.build_decision(value)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update({"unexpected": True}), "unknown fields"),
        (
            lambda value: value["semantic_review"].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["merge_evidence"].update({"unexpected": True}),
            "unknown fields",
        ),
        (
            lambda value: value["semantic_review"]["findings"][0].update(
                {"unexpected": True}
            ),
            "unknown fields",
        ),
        (
            lambda value: value["merge_evidence"]["required_checks"][0].update(
                {"unexpected": True}
            ),
            "unknown fields",
        ),
        (lambda value: value.update({"pull_request_number": True}), "integer"),
        (
            lambda value: value["semantic_review"].update({"status": "running"}),
            "semantic_review.status",
        ),
        (
            lambda value: value["merge_evidence"].update(
                {"coverage_state": "green"}
            ),
            "coverage_state",
        ),
        (
            lambda value: value["semantic_review"]["findings"][0].update(
                {"path": "../secret"}
            ),
            "relative source path",
        ),
        (
            lambda value: value["semantic_review"]["findings"][0].update({"line": 0}),
            "positive integer",
        ),
    ],
)
def test_strict_schema_rejects_unknown_fields_and_scalar_confusion(
    mutate: Any, message: str
) -> None:
    """Every evidence layer fails closed on malformed control data."""
    value = envelope(findings=[finding()])
    mutate(value)
    with pytest.raises(decision.DecisionValidationError, match=message):
        decision.build_decision(value)


def test_duplicate_finding_and_check_names_are_rejected() -> None:
    """Duplicate semantic or check identities cannot inflate evidence counts."""
    with pytest.raises(decision.DecisionValidationError, match="finding_id"):
        decision.build_decision(envelope(findings=[finding(), finding()]))

    with pytest.raises(decision.DecisionValidationError, match="check name"):
        decision.build_decision(envelope(checks=[check("CI"), check("ci")]))


def test_validation_helpers_reject_remaining_invalid_shapes_and_scalars() -> None:
    """Primitive schema helpers must reject unsupported JSON shapes and scalar values."""
    with pytest.raises(decision.DecisionValidationError, match="must be an array"):
        decision.array_value({}, "array")
    with pytest.raises(decision.DecisionValidationError, match="non-empty text"):
        decision.text_value(" ", "text")
    with pytest.raises(decision.DecisionValidationError, match="must be boolean"):
        decision.bool_value(1, "flag")
    with pytest.raises(decision.DecisionValidationError, match="commit SHA"):
        decision.commit_sha_value("main", "head")


def test_top_level_schema_and_repository_coordinates_are_strict() -> None:
    """Decision identity must use the exact schema version and owner/name repository form."""
    wrong_version = envelope()
    wrong_version["schema_version"] = "2.0"
    with pytest.raises(decision.DecisionValidationError, match="schema_version"):
        decision.build_decision(wrong_version)

    invalid_repository = envelope()
    invalid_repository["repository"] = "missing-slash"
    with pytest.raises(decision.DecisionValidationError, match="owner/name"):
        decision.build_decision(invalid_repository)
