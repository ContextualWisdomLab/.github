#!/usr/bin/env python3
"""Freeze blinded independent expert annotations into exact-head gold evidence."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

from opencode_review_adjudication_primitives import (  # noqa: E402
    AdjudicationError,
    array_value,
    bool_value,
    commit_sha_value,
    content_digest,
    digest_value,
    object_value,
    reject,
    reject_constant,
    strict_pairs,
    text_value,
    unique_text_values,
)
from opencode_review_adjudication_annotations import (  # noqa: E402
    validate_case,
    validate_expert,
)
from opencode_review_adjudication_decisions import (  # noqa: E402
    validate_adjudication,
)

def reference_once(
    identifier: str,
    known: set[str],
    used: set[str],
    path: str,
    expert_label: str,
) -> None:
    """Require one known expert finding and consume it exactly once."""
    if identifier not in known:
        reject(f"{path} references unknown expert {expert_label} finding {identifier!r}")
    if identifier in used:
        reject(f"{path} references expert {expert_label} finding {identifier!r} more than once")
    used.add(identifier)


def adjudicate_case(
    raw_expert_a: Any, raw_expert_b: Any, raw_adjudication: Any
) -> dict[str, Any]:
    """Validate, reconcile, and freeze one complete exact-head gold case."""
    expert_a = validate_expert(raw_expert_a, "expert_a")
    expert_b = validate_expert(raw_expert_b, "expert_b")
    decision_record = validate_adjudication(raw_adjudication)
    if not (expert_a["case"] == expert_b["case"] == decision_record["case"]):
        reject("expert and adjudicator case identity must match exactly")
    actors = {
        expert_a["expert_id"],
        expert_b["expert_id"],
        decision_record["adjudicator_id"],
    }
    if len(actors) != 3:
        reject("two experts and adjudicator must be distinct pseudonymous roles")

    a_known = {item["expert_finding_id"] for item in expert_a["findings"]}
    b_known = {item["expert_finding_id"] for item in expert_b["findings"]}
    a_used: set[str] = set()
    b_used: set[str] = set()
    gold: list[dict[str, Any]] = []
    accepted_both = 0
    accepted_a_only = 0
    accepted_b_only = 0
    rejected_sources = 0
    for index, item in enumerate(decision_record["decisions"]):
        path = f"adjudication.decisions[{index}]"
        for identifier in item["expert_a_finding_ids"]:
            reference_once(identifier, a_known, a_used, path, "A")
        for identifier in item["expert_b_finding_ids"]:
            reference_once(identifier, b_known, b_used, path, "B")
        if item["outcome"] == "accept":
            has_a = bool(item["expert_a_finding_ids"])
            has_b = bool(item["expert_b_finding_ids"])
            accepted_both += int(has_a and has_b)
            accepted_a_only += int(has_a and not has_b)
            accepted_b_only += int(has_b and not has_a)
            gold.append(
                {
                    "finding_id": item["gold_finding_id"],
                    "path": item["path"],
                    "line": item["line"],
                    "defect_class": item["defect_class"],
                    "severity": item["severity"],
                    "trigger": item["trigger"],
                    "impact": item["impact"],
                    "root_cause": item["root_cause"],
                    "fix_direction": item["fix_direction"],
                    "regression_target": item["regression_target"],
                    "source_decision_id": item["decision_id"],
                }
            )
        else:
            rejected_sources += len(item["expert_a_finding_ids"]) + len(
                item["expert_b_finding_ids"]
            )
    uncovered_a = sorted(a_known - a_used)
    uncovered_b = sorted(b_known - b_used)
    if uncovered_a or uncovered_b:
        details = []
        if uncovered_a:
            details.append(f"expert A: {', '.join(uncovered_a)}")
        if uncovered_b:
            details.append(f"expert B: {', '.join(uncovered_b)}")
        reject(f"expert findings are uncovered by adjudication: {'; '.join(details)}")

    gold.sort(key=lambda item: item["finding_id"])
    annotation_receipts = sorted(
        [
            {
                "annotation_id": expert_a["annotation_id"],
                "expert_id": expert_a["expert_id"],
                "annotation_sha256": content_digest(expert_a),
            },
            {
                "annotation_id": expert_b["annotation_id"],
                "expert_id": expert_b["expert_id"],
                "annotation_sha256": content_digest(expert_b),
            },
        ],
        key=lambda item: item["expert_id"],
    )
    adjudication_receipt = {
        "adjudication_id": decision_record["adjudication_id"],
        "adjudicator_id": decision_record["adjudicator_id"],
        "adjudication_sha256": content_digest(decision_record),
    }
    report_without_digest = {
        "schema_version": "1.0",
        "case": expert_a["case"],
        "gold_findings": gold,
        "agreement_metrics": {
            "expert_a_findings": len(a_known),
            "expert_b_findings": len(b_known),
            "accepted_gold_findings": len(gold),
            "accepted_by_both_experts": accepted_both,
            "accepted_from_expert_a_only": accepted_a_only,
            "accepted_from_expert_b_only": accepted_b_only,
            "rejected_source_findings": rejected_sources,
        },
        "annotation_receipts": annotation_receipts,
        "adjudication_receipt": adjudication_receipt,
    }
    return {
        **report_without_digest,
        "freeze_sha256": content_digest(report_without_digest),
    }



def load_json(path: Path) -> Any:
    """Load strict UTF-8 JSON with bounded stable validation errors."""
    try:
        return json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=strict_pairs,
            parse_constant=reject_constant,
        )
    except (OSError, json.JSONDecodeError) as error:
        reject(f"cannot load adjudication evidence: {error}")


def write_text(path: Path, content: str) -> None:
    """Atomically replace one UTF-8 output after creating its parent directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the adjudicator CLI and return a stable validation status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expert-a", type=Path, required=True)
    parser.add_argument("--expert-b", type=Path, required=True)
    parser.add_argument("--adjudication", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        report = adjudicate_case(
            load_json(arguments.expert_a),
            load_json(arguments.expert_b),
            load_json(arguments.adjudication),
        )
    except AdjudicationError as error:
        print(f"adjudication evidence rejected: {error}", file=sys.stderr)
        return 2
    write_text(
        arguments.output,
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
