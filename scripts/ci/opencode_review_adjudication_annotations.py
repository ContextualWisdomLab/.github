"""Validate blinded expert annotations for exact-head code-review gold evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from opencode_review_adjudication_primitives import (
    VALID_SEVERITIES,
    REPOSITORY_RE,
    array_value,
    bool_value,
    commit_sha_value,
    count_value,
    digest_value,
    object_value,
    reject,
    require_exact_fields,
    source_path_value,
    text_value,
)

def validate_case(raw_value: Any, path: str) -> dict[str, Any]:
    """Validate one immutable repository, pull request, and evidence identity."""
    value = object_value(raw_value, path)
    require_exact_fields(
        value,
        path,
        {
            "case_id",
            "repository",
            "pull_request_number",
            "base_sha",
            "head_sha",
            "diff_sha256",
            "context_sha256",
        },
    )
    repository = text_value(value.get("repository"), f"{path}.repository")
    if not REPOSITORY_RE.fullmatch(repository):
        reject(f"{path}.repository must use owner/name")
    return {
        "case_id": text_value(value.get("case_id"), f"{path}.case_id"),
        "repository": repository,
        "pull_request_number": count_value(
            value.get("pull_request_number"),
            f"{path}.pull_request_number",
            positive=True,
        ),
        "base_sha": commit_sha_value(value.get("base_sha"), f"{path}.base_sha"),
        "head_sha": commit_sha_value(value.get("head_sha"), f"{path}.head_sha"),
        "diff_sha256": digest_value(
            value.get("diff_sha256"), f"{path}.diff_sha256"
        ),
        "context_sha256": digest_value(
            value.get("context_sha256"), f"{path}.context_sha256"
        ),
    }


def finding_fields(
    value: Mapping[str, Any], path: str, *, identifier_field: str
) -> dict[str, Any]:
    """Validate the complete source-defect contract shared by experts and gold."""
    severity = text_value(value.get("severity"), f"{path}.severity").casefold()
    if severity not in VALID_SEVERITIES:
        reject(f"{path}.severity is invalid")
    return {
        identifier_field: text_value(
            value.get(identifier_field), f"{path}.{identifier_field}"
        ),
        "path": source_path_value(value.get("path"), f"{path}.path"),
        "line": count_value(value.get("line"), f"{path}.line", positive=True),
        "defect_class": text_value(
            value.get("defect_class"), f"{path}.defect_class"
        ).casefold(),
        "severity": severity,
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


def validate_expert(raw_value: Any, path: str) -> dict[str, Any]:
    """Validate one blinded, exhaustive, full-context independent annotation."""
    value = object_value(raw_value, path)
    require_exact_fields(
        value,
        path,
        {
            "schema_version",
            "annotation_id",
            "expert_id",
            "case",
            "reviewer_outputs_hidden",
            "full_repository_context_reviewed",
            "no_additional_findings",
            "findings",
        },
    )
    if value.get("schema_version") != "1.0":
        reject(f"{path}.schema_version must equal '1.0'")
    if not bool_value(
        value.get("reviewer_outputs_hidden"), f"{path}.reviewer_outputs_hidden"
    ):
        reject(f"{path}.reviewer_outputs_hidden must be true")
    if not bool_value(
        value.get("full_repository_context_reviewed"),
        f"{path}.full_repository_context_reviewed",
    ):
        reject(f"{path}.full_repository_context_reviewed must be true")
    if not bool_value(
        value.get("no_additional_findings"), f"{path}.no_additional_findings"
    ):
        reject(f"{path}.no_additional_findings must be true")
    seen: set[str] = set()
    findings: list[dict[str, Any]] = []
    finding_allowed = {
        "expert_finding_id",
        "path",
        "line",
        "defect_class",
        "severity",
        "trigger",
        "impact",
        "root_cause",
        "fix_direction",
        "regression_target",
    }
    for index, raw_finding in enumerate(array_value(value.get("findings"), f"{path}.findings")):
        finding_path = f"{path}.findings[{index}]"
        finding_value = object_value(raw_finding, finding_path)
        require_exact_fields(finding_value, finding_path, finding_allowed)
        finding = finding_fields(
            finding_value, finding_path, identifier_field="expert_finding_id"
        )
        identifier = finding["expert_finding_id"]
        if identifier in seen:
            reject(f"{finding_path}.expert_finding_id duplicates {identifier!r}")
        seen.add(identifier)
        findings.append(finding)
    return {
        "schema_version": "1.0",
        "annotation_id": text_value(
            value.get("annotation_id"), f"{path}.annotation_id"
        ),
        "expert_id": text_value(value.get("expert_id"), f"{path}.expert_id"),
        "case": validate_case(value.get("case"), f"{path}.case"),
        "reviewer_outputs_hidden": True,
        "full_repository_context_reviewed": True,
        "no_additional_findings": True,
        "findings": findings,
    }


