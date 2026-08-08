"""Routing tests for risk-adaptive OpenCode shadow orchestration."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
if str(TEST_DIR) not in sys.path:
    sys.path.insert(0, str(TEST_DIR))

from opencode_review_shadow_test_support import changed_file, request, shadow


def roles(plan: dict[str, object]) -> list[str]:
    """Return ordered attempt roles from one normalized shadow plan."""
    return [item["role_code"] for item in plan["attempts"]]  # type: ignore[index]


def test_low_risk_documentation_change_uses_one_detector_and_one_verifier() -> None:
    """Small documentation-only changes must avoid unnecessary multi-agent compute."""
    plan = shadow.build_plan(
        request(
            files=[
                changed_file(
                    "docs/usage.md",
                    language="markdown",
                    additions=12,
                    deletions=2,
                    risk_tags=["documentation"],
                )
            ]
        )
    )
    assert plan["risk_tier"] == "low"
    assert plan["diff_size_bucket"] == "small"
    assert roles(plan) == ["general_detector", "verifier"]
    assert [item["reasoning_effort"] for item in plan["attempts"]] == [
        "low",
        "medium",
    ]
    assert plan["shadow_mode"] is True
    assert plan["publication_enabled"] is False
    assert plan["maximum_recursive_verification_depth"] == 0


def test_ordinary_source_change_uses_general_detector_and_independent_verifier() -> None:
    """Ordinary source changes receive a semantic detector plus a distinct verifier."""
    plan = shadow.build_plan(request())
    assert plan["risk_tier"] == "standard"
    assert roles(plan) == ["general_detector", "verifier"]
    detector, verifier = plan["attempts"]
    assert detector["model_id"] != verifier["model_id"]
    assert detector["phase"] == "detector"
    assert verifier["phase"] == "verifier"
    assert detector["reasoning_effort"] == "medium"
    assert verifier["reasoning_effort"] == "medium"


def test_security_workflow_and_data_model_changes_add_specialists() -> None:
    """Material trust changes allocate diverse specialists and a high-effort verifier."""
    plan = shadow.build_plan(
        request(
            files=[
                changed_file(
                    ".github/workflows/release.yml",
                    language="yaml",
                    additions=90,
                    deletions=12,
                    risk_tags=["security", "workflow", "release"],
                ),
                changed_file(
                    "database/migrations/0009_account_policy.sql",
                    language="sql",
                    additions=80,
                    deletions=10,
                    risk_tags=["data_model", "migration"],
                ),
            ]
        )
    )
    assert plan["risk_tier"] == "critical"
    assert plan["diff_size_bucket"] == "medium"
    assert roles(plan) == [
        "general_detector",
        "security_detector",
        "workflow_detector",
        "data_model_detector",
        "verifier",
        "recursive_verifier",
    ]
    assert len(
        {
            (item["provider_id"], item["model_id"])
            for item in plan["attempts"]
            if item["phase"] == "detector"
        }
    ) >= 3
    assert plan["maximum_recursive_verification_depth"] == 1
    assert all(item["reasoning_effort"] == "high" for item in plan["attempts"])
    assert set(plan["risk_reasons"]) >= {
        "security",
        "workflow",
        "release",
        "data_model",
        "migration",
    }


def test_numerical_and_experience_changes_route_to_role_specific_detectors() -> None:
    """Numerical and buyer-facing changes use relevant specialists without fixed topology."""
    plan = shadow.build_plan(
        request(
            files=[
                changed_file(
                    "crates/estimator/src/kernel.rs",
                    language="rust",
                    additions=310,
                    deletions=70,
                    risk_tags=["numerical", "performance"],
                ),
                changed_file(
                    "apps/web/src/ReportView.tsx",
                    language="typescript",
                    additions=100,
                    deletions=20,
                    risk_tags=["experience", "accessibility", "public_api"],
                ),
            ]
        )
    )
    assert plan["risk_tier"] == "high"
    assert roles(plan) == [
        "general_detector",
        "numerical_detector",
        "experience_detector",
        "verifier",
    ]
    assert plan["diff_size_bucket"] == "large"
    assert plan["maximum_recursive_verification_depth"] == 0


def test_detector_budget_is_fail_closed_instead_of_silently_dropping_specialists() -> None:
    """A detector limit below the required specialist set must reject the plan."""
    value = request(
        maximum_detector_attempts=2,
        files=[
            changed_file(
                ".github/workflows/security.yml",
                language="yaml",
                risk_tags=["security", "workflow", "release"],
            )
        ],
    )
    with pytest.raises(shadow.InsufficientPoolError, match="detector attempt budget"):
        shadow.build_plan(value)


def test_missing_role_or_model_diversity_is_rejected() -> None:
    """High-risk review must not degrade to a general model or self-verification."""
    no_security = request()
    no_security["changed_files"] = [
        changed_file("src/auth.py", risk_tags=["security"])
    ]
    no_security["policy"]["model_pool"] = [
        item
        for item in no_security["policy"]["model_pool"]
        if "security_detector" not in item["role_codes"]
    ]
    with pytest.raises(shadow.InsufficientPoolError, match="security_detector"):
        shadow.build_plan(no_security)

    no_verifier_diversity = request()
    only = no_verifier_diversity["policy"]["model_pool"][0]
    only["role_codes"].append("verifier")
    no_verifier_diversity["policy"]["model_pool"] = [only]
    with pytest.raises(shadow.InsufficientPoolError, match="independent verifier"):
        shadow.build_plan(no_verifier_diversity)


def test_same_request_and_policy_produce_one_content_addressed_plan() -> None:
    """Routing is deterministic and records exact evidence and policy receipts."""
    first = shadow.build_plan(request())
    second = shadow.build_plan(request())
    assert first == second
    assert first["input_sha256"].startswith("sha256:")
    assert first["plan_sha256"].startswith("sha256:")
    assert all(item["prompt_sha256"].startswith("sha256:") for item in first["attempts"])
    assert all("credential" not in key for item in first["attempts"] for key in item)
