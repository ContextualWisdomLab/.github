"""Validate blinded adjudication decisions for exact-head gold evidence."""

from __future__ import annotations

from typing import Any

from opencode_review_adjudication_primitives import (
    VALID_SEVERITIES,
    array_value,
    bool_value,
    object_value,
    optional_positive_count,
    optional_text,
    reject,
    require_exact_fields,
    source_path_value,
    text_value,
    unique_text_values,
)
from opencode_review_adjudication_annotations import validate_case

def validate_decision(raw_value: Any, path: str) -> dict[str, Any]:
    """Validate one source-linked accepted-gold or rejected-report decision."""
    value = object_value(raw_value, path)
    fields = {
        "decision_id",
        "expert_a_finding_ids",
        "expert_b_finding_ids",
        "outcome",
        "gold_finding_id",
        "path",
        "line",
        "defect_class",
        "severity",
        "trigger",
        "impact",
        "root_cause",
        "fix_direction",
        "regression_target",
        "reason",
    }
    require_exact_fields(value, path, fields)
    a_ids = unique_text_values(
        value.get("expert_a_finding_ids"), f"{path}.expert_a_finding_ids"
    )
    b_ids = unique_text_values(
        value.get("expert_b_finding_ids"), f"{path}.expert_b_finding_ids"
    )
    if not a_ids and not b_ids:
        reject(f"{path} must reference at least one expert finding")
    outcome = text_value(value.get("outcome"), f"{path}.outcome").casefold()
    if outcome not in {"accept", "reject"}:
        reject(f"{path}.outcome must equal accept or reject")
    decision = {
        "decision_id": text_value(value.get("decision_id"), f"{path}.decision_id"),
        "expert_a_finding_ids": a_ids,
        "expert_b_finding_ids": b_ids,
        "outcome": outcome,
        "gold_finding_id": optional_text(
            value.get("gold_finding_id"), f"{path}.gold_finding_id"
        ),
        "path": optional_text(value.get("path"), f"{path}.path"),
        "line": optional_positive_count(value.get("line"), f"{path}.line"),
        "defect_class": optional_text(
            value.get("defect_class"), f"{path}.defect_class"
        ),
        "severity": optional_text(value.get("severity"), f"{path}.severity"),
        "trigger": optional_text(value.get("trigger"), f"{path}.trigger"),
        "impact": optional_text(value.get("impact"), f"{path}.impact"),
        "root_cause": optional_text(
            value.get("root_cause"), f"{path}.root_cause"
        ),
        "fix_direction": optional_text(
            value.get("fix_direction"), f"{path}.fix_direction"
        ),
        "regression_target": optional_text(
            value.get("regression_target"), f"{path}.regression_target"
        ),
        "reason": text_value(value.get("reason"), f"{path}.reason"),
    }
    evidence_fields = (
        "path",
        "line",
        "defect_class",
        "severity",
        "trigger",
        "impact",
        "root_cause",
        "fix_direction",
        "regression_target",
    )
    if outcome == "accept":
        if decision["gold_finding_id"] is None:
            reject(f"{path}.gold_finding_id is required for accepted gold")
        for name in evidence_fields:
            if decision[name] is None:
                reject(f"accepted decision {path} requires {name}")
        decision["path"] = source_path_value(decision["path"], f"{path}.path")
        decision["defect_class"] = decision["defect_class"].casefold()
        decision["severity"] = decision["severity"].casefold()
        if decision["severity"] not in VALID_SEVERITIES:
            reject(f"{path}.severity is invalid")
    else:
        if decision["gold_finding_id"] is not None:
            reject(f"rejected decision {path} must not mint gold")
        if any(decision[name] is not None for name in evidence_fields):
            reject(f"rejected decision {path} must not carry accepted gold evidence")
    return decision


def validate_adjudication(raw_value: Any, path: str = "adjudication") -> dict[str, Any]:
    """Validate one identity-blinded decision record and its unique decisions."""
    value = object_value(raw_value, path)
    require_exact_fields(
        value,
        path,
        {
            "schema_version",
            "adjudication_id",
            "adjudicator_id",
            "case",
            "reviewer_identities_hidden",
            "reviewer_outputs_hidden",
            "no_defects_confirmed",
            "decisions",
        },
    )
    if value.get("schema_version") != "1.0":
        reject(f"{path}.schema_version must equal '1.0'")
    if not bool_value(
        value.get("reviewer_identities_hidden"),
        f"{path}.reviewer_identities_hidden",
    ):
        reject(f"{path}.reviewer_identities_hidden must be true")
    if not bool_value(
        value.get("reviewer_outputs_hidden"),
        f"{path}.reviewer_outputs_hidden",
    ):
        reject(f"{path}.reviewer_outputs_hidden must be true")
    raw_no_defects = value.get("no_defects_confirmed")
    no_defects_confirmed = (
        False
        if raw_no_defects is None
        else bool_value(raw_no_defects, f"{path}.no_defects_confirmed")
    )
    decisions: list[dict[str, Any]] = []
    decision_ids: set[str] = set()
    gold_ids: set[str] = set()
    for index, raw_decision in enumerate(
        array_value(value.get("decisions"), f"{path}.decisions")
    ):
        decision_path = f"{path}.decisions[{index}]"
        decision = validate_decision(raw_decision, decision_path)
        decision_id = decision["decision_id"]
        if decision_id in decision_ids:
            reject(f"{decision_path}.decision_id duplicates {decision_id!r}")
        decision_ids.add(decision_id)
        gold_id = decision["gold_finding_id"]
        if gold_id is not None:
            if gold_id in gold_ids:
                reject(f"{decision_path}.gold_finding_id duplicates {gold_id!r}")
            gold_ids.add(gold_id)
        decisions.append(decision)
    if not decisions:
        if not no_defects_confirmed:
            reject(
                f"{path}.decisions must not be empty unless "
                "no_defects_confirmed is true"
            )
    elif no_defects_confirmed:
        reject(f"{path}.no_defects_confirmed must be false when decisions are present")
    return {
        "schema_version": "1.0",
        "adjudication_id": text_value(
            value.get("adjudication_id"), f"{path}.adjudication_id"
        ),
        "adjudicator_id": text_value(
            value.get("adjudicator_id"), f"{path}.adjudicator_id"
        ),
        "case": validate_case(value.get("case"), f"{path}.case"),
        "reviewer_identities_hidden": True,
        "reviewer_outputs_hidden": True,
        "no_defects_confirmed": no_defects_confirmed,
        "decisions": decisions,
    }


