#!/usr/bin/env python3
"""Build independent semantic-review and merge-readiness decisions."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from opencode_review_decision_primitives import (  # noqa: E402
    HARD_BLOCKING_STATES,
    UNKNOWN_STATES,
    DecisionValidationError,
    array_value,
    bool_value,
    commit_sha_value,
    content_digest,
    load_json,
    reject_constant,
    strict_pairs,
    text_value,
    write_text,
)
from opencode_review_decision_validation import validate_decision_input  # noqa: E402


def blocker(
    blocker_code: str, evidence_name: str, state: str, check_name: str | None = None
) -> dict[str, Any]:
    """Build one path-free infrastructure or policy blocker."""
    return {
        "blocker_code": blocker_code,
        "evidence_name": evidence_name,
        "state": state,
        "check_name": check_name,
    }


def classify_review_verdict(semantic_review: Mapping[str, Any]) -> str:
    """Choose a semantic verdict without consulting merge-readiness evidence."""
    if semantic_review["status"] != "complete":
        return "ABSTAIN"
    findings = semantic_review["findings"]
    if any(item["blocking"] for item in findings):
        return "REQUEST_CHANGES"
    return "COMMENT" if findings else "APPROVE"


def collect_blockers(merge_evidence: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Collect non-successful policy evidence without source-location authority."""
    blockers: list[dict[str, Any]] = []
    policy_surfaces = (
        (
            "coverage_state",
            "coverage_not_successful",
            "coverage",
        ),
        (
            "independent_approval_state",
            "independent_approval_not_successful",
            "independent_approval",
        ),
        (
            "branch_protection_state",
            "branch_protection_not_successful",
            "branch_protection",
        ),
    )
    for field, code, evidence_name in policy_surfaces:
        state = merge_evidence[field]
        if state != "success":
            blockers.append(blocker(code, evidence_name, state))
    for check in merge_evidence["required_checks"]:
        if check["required"] and check["state"] != "success":
            blockers.append(
                blocker(
                    "required_check_not_successful",
                    "required_check",
                    check["state"],
                    check["name"],
                )
            )
    return blockers


def classify_merge_readiness(
    review_verdict: str, blockers: Sequence[Mapping[str, Any]]
) -> str:
    """Classify merge readiness using fail-closed policy evidence and latency states."""
    if review_verdict == "REQUEST_CHANGES":
        return "BLOCKED"
    blocker_states = {item["state"] for item in blockers}
    if blocker_states & HARD_BLOCKING_STATES:
        return "BLOCKED"
    if review_verdict == "ABSTAIN" or blocker_states & UNKNOWN_STATES:
        return "UNKNOWN"
    return "READY"


def build_decision(raw_value: Any) -> dict[str, Any]:
    """Build one deterministic exact-head decision with independent channels."""
    value = validate_decision_input(raw_value)
    semantic_review = value["semantic_review"]
    merge_evidence = value["merge_evidence"]
    review_verdict = classify_review_verdict(semantic_review)
    blockers = collect_blockers(merge_evidence)
    required_checks = [item for item in merge_evidence["required_checks"] if item["required"]]
    advisory_checks = [item for item in merge_evidence["required_checks"] if not item["required"]]
    report_without_digest = {
        "schema_version": "1.0",
        "decision_id": value["decision_id"],
        "quality_policy_version": value["quality_policy_version"],
        "repository": value["repository"],
        "pull_request_number": value["pull_request_number"],
        "base_sha": value["base_sha"],
        "head_sha": value["head_sha"],
        "semantic_status": semantic_review["status"],
        "review_verdict": review_verdict,
        "merge_readiness": classify_merge_readiness(review_verdict, blockers),
        "findings": semantic_review["findings"],
        "infrastructure_blockers": blockers,
        "evidence_manifest": {
            "input_sha256": content_digest(value),
            "semantic_reviewed_head_sha": semantic_review["reviewed_head_sha"],
            "merge_evidence_head_sha": merge_evidence["evidence_head_sha"],
            "coverage_state": merge_evidence["coverage_state"],
            "independent_approval_state": merge_evidence[
                "independent_approval_state"
            ],
            "branch_protection_state": merge_evidence["branch_protection_state"],
            "required_check_count": len(required_checks),
            "successful_required_check_count": sum(
                item["state"] == "success" for item in required_checks
            ),
            "advisory_check_count": len(advisory_checks),
            "checks": merge_evidence["required_checks"],
        },
    }
    return {
        **report_without_digest,
        "decision_sha256": content_digest(report_without_digest),
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a human-readable decision without turning blockers into source defects."""
    lines = [
        "# OpenCode review decision",
        "",
        f"Review verdict: **{report['review_verdict']}**  ",
        f"Merge readiness: **{report['merge_readiness']}**  ",
        f"Semantic status: **{report['semantic_status']}**  ",
        f"Exact head: `{report['head_sha']}`",
        "",
        "## Semantic findings",
        "",
    ]
    if report["findings"]:
        for finding in report["findings"]:
            lines.extend(
                [
                    f"- **{finding['severity'].upper()}** `{finding['path']}:{finding['line']}` — {finding['trigger']}",
                    f"  - Impact: {finding['impact']}",
                    f"  - Root cause: {finding['root_cause']}",
                    f"  - Fix direction: {finding['fix_direction']}",
                    f"  - Regression target: {finding['regression_target']}",
                ]
            )
    else:
        lines.append("- None.")
    lines.extend(["", "## Infrastructure and policy blockers", ""])
    if report["infrastructure_blockers"]:
        for item in report["infrastructure_blockers"]:
            suffix = f" / check `{item['check_name']}`" if item["check_name"] else ""
            lines.append(
                f"- `{item['evidence_name']}` — `{item['state']}` ({item['blocker_code']}){suffix}"
            )
    else:
        lines.append("- None.")
    lines.extend(
        [
            "",
            "## Evidence receipt",
            "",
            f"- Input: `{report['evidence_manifest']['input_sha256']}`",
            f"- Decision: `{report['decision_sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the decision CLI and return a stable validation status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        report = build_decision(load_json(arguments.input))
    except DecisionValidationError as error:
        print(f"decision evidence rejected: {error}", file=sys.stderr)
        return 2
    write_text(
        arguments.json_output,
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
    )
    write_text(arguments.markdown_output, render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
