#!/usr/bin/env python3
"""Validate exact-head semantic and merge-policy evidence."""

from __future__ import annotations

from typing import Any

from opencode_review_decision_primitives import (
    REPOSITORY_RE,
    VALID_EVIDENCE_STATES,
    VALID_SEMANTIC_STATUSES,
    VALID_SEVERITIES,
    array_value,
    bool_value,
    commit_sha_value,
    enum_value,
    object_value,
    optional_commit_sha_value,
    positive_int_value,
    reject,
    require_exact_fields,
    source_path_value,
    text_value,
)


def validate_finding(raw_value: Any, path: str) -> dict[str, Any]:
    """Validate one complete semantic source finding."""
    value = object_value(raw_value, path)
    require_exact_fields(
        value,
        path,
        {
            "finding_id",
            "defect_class",
            "severity",
            "blocking",
            "path",
            "line",
            "trigger",
            "impact",
            "root_cause",
            "fix_direction",
            "regression_target",
        },
    )
    return {
        "finding_id": text_value(value.get("finding_id"), f"{path}.finding_id"),
        "defect_class": text_value(
            value.get("defect_class"), f"{path}.defect_class"
        ).casefold(),
        "severity": enum_value(
            value.get("severity"), f"{path}.severity", VALID_SEVERITIES
        ),
        "blocking": bool_value(value.get("blocking"), f"{path}.blocking"),
        "path": source_path_value(value.get("path"), f"{path}.path"),
        "line": positive_int_value(value.get("line"), f"{path}.line"),
        "trigger": text_value(value.get("trigger"), f"{path}.trigger"),
        "impact": text_value(value.get("impact"), f"{path}.impact"),
        "root_cause": text_value(value.get("root_cause"), f"{path}.root_cause"),
        "fix_direction": text_value(
            value.get("fix_direction"), f"{path}.fix_direction"
        ),
        "regression_target": text_value(
            value.get("regression_target"), f"{path}.regression_target"
        ),
    }


def validate_semantic_review(
    raw_value: Any, expected_head_sha: str
) -> dict[str, Any]:
    """Validate semantic review evidence independently from merge policy evidence."""
    value = object_value(raw_value, "semantic_review")
    require_exact_fields(
        value,
        "semantic_review",
        {"status", "reviewed_head_sha", "findings"},
    )
    status = enum_value(
        value.get("status"), "semantic_review.status", VALID_SEMANTIC_STATUSES
    )
    reviewed_head_sha = optional_commit_sha_value(
        value.get("reviewed_head_sha"), "semantic_review.reviewed_head_sha"
    )
    raw_findings = array_value(value.get("findings"), "semantic_review.findings")
    if status != "complete":
        if reviewed_head_sha is not None:
            reject(
                "semantic_review.reviewed_head_sha must be null when semantic review is incomplete"
            )
        if raw_findings:
            reject("incomplete semantic review must not contain findings")
        return {
            "status": status,
            "reviewed_head_sha": None,
            "findings": [],
        }
    if reviewed_head_sha != expected_head_sha:
        reject(
            "semantic_review.reviewed_head_sha must equal the exact decision head_sha"
        )
    findings: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_finding in enumerate(raw_findings):
        finding = validate_finding(
            raw_finding, f"semantic_review.findings[{index}]"
        )
        identity = finding["finding_id"].casefold()
        if identity in seen_ids:
            reject(
                f"semantic_review.findings[{index}].finding_id duplicates {finding['finding_id']!r}"
            )
        seen_ids.add(identity)
        findings.append(finding)
    findings.sort(key=lambda item: item["finding_id"].casefold())
    return {
        "status": status,
        "reviewed_head_sha": reviewed_head_sha,
        "findings": findings,
    }


def validate_check(raw_value: Any, path: str, expected_head_sha: str) -> dict[str, Any]:
    """Validate one exact-head required or advisory check record."""
    value = object_value(raw_value, path)
    require_exact_fields(value, path, {"name", "state", "required", "head_sha"})
    head_sha = commit_sha_value(value.get("head_sha"), f"{path}.head_sha")
    if head_sha != expected_head_sha:
        reject(f"{path}.head_sha must equal the exact decision head_sha")
    return {
        "name": text_value(value.get("name"), f"{path}.name"),
        "state": enum_value(
            value.get("state"), f"{path}.state", VALID_EVIDENCE_STATES
        ),
        "required": bool_value(value.get("required"), f"{path}.required"),
        "head_sha": head_sha,
    }


def validate_merge_evidence(
    raw_value: Any, expected_head_sha: str
) -> dict[str, Any]:
    """Validate exact-head coverage, approval, protection, and check evidence."""
    value = object_value(raw_value, "merge_evidence")
    require_exact_fields(
        value,
        "merge_evidence",
        {
            "evidence_head_sha",
            "coverage_state",
            "independent_approval_state",
            "branch_protection_state",
            "required_checks",
        },
    )
    evidence_head_sha = commit_sha_value(
        value.get("evidence_head_sha"), "merge_evidence.evidence_head_sha"
    )
    if evidence_head_sha != expected_head_sha:
        reject("merge_evidence.evidence_head_sha must equal the exact decision head_sha")
    checks: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for index, raw_check in enumerate(
        array_value(value.get("required_checks"), "merge_evidence.required_checks")
    ):
        path = f"merge_evidence.required_checks[{index}]"
        check = validate_check(raw_check, path, expected_head_sha)
        normalized_name = check["name"].casefold()
        if normalized_name in seen_names:
            reject(f"{path}.name duplicates check name {check['name']!r}")
        seen_names.add(normalized_name)
        checks.append(check)
    checks.sort(key=lambda item: item["name"].casefold())
    return {
        "evidence_head_sha": evidence_head_sha,
        "coverage_state": enum_value(
            value.get("coverage_state"),
            "merge_evidence.coverage_state",
            VALID_EVIDENCE_STATES,
        ),
        "independent_approval_state": enum_value(
            value.get("independent_approval_state"),
            "merge_evidence.independent_approval_state",
            VALID_EVIDENCE_STATES,
        ),
        "branch_protection_state": enum_value(
            value.get("branch_protection_state"),
            "merge_evidence.branch_protection_state",
            VALID_EVIDENCE_STATES,
        ),
        "required_checks": checks,
    }


def validate_decision_input(raw_value: Any) -> dict[str, Any]:
    """Validate and normalize one complete exact-head decision input."""
    value = object_value(raw_value, "decision")
    require_exact_fields(
        value,
        "decision",
        {
            "schema_version",
            "decision_id",
            "quality_policy_version",
            "repository",
            "pull_request_number",
            "base_sha",
            "head_sha",
            "semantic_review",
            "merge_evidence",
        },
    )
    if value.get("schema_version") != "1.0":
        reject("decision.schema_version must equal '1.0'")
    repository = text_value(value.get("repository"), "decision.repository")
    if not REPOSITORY_RE.fullmatch(repository):
        reject("decision.repository must use owner/name")
    head_sha = commit_sha_value(value.get("head_sha"), "decision.head_sha")
    normalized = {
        "schema_version": "1.0",
        "decision_id": text_value(value.get("decision_id"), "decision.decision_id"),
        "quality_policy_version": text_value(
            value.get("quality_policy_version"), "decision.quality_policy_version"
        ),
        "repository": repository,
        "pull_request_number": positive_int_value(
            value.get("pull_request_number"), "decision.pull_request_number"
        ),
        "base_sha": commit_sha_value(value.get("base_sha"), "decision.base_sha"),
        "head_sha": head_sha,
        "semantic_review": validate_semantic_review(
            value.get("semantic_review"), head_sha
        ),
        "merge_evidence": validate_merge_evidence(
            value.get("merge_evidence"), head_sha
        ),
    }
    return normalized
