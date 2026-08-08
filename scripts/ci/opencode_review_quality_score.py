#!/usr/bin/env python3
"""Validate and score empirical automated-review quality evidence."""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

VALID_MODES = {"historical_lifecycle", "head_matched_gold"}
VALID_BUCKETS = {"small", "medium", "large"}
VALID_SEVERITIES = {"critical", "high", "medium", "low"}
REPOSITORY_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class BenchmarkValidationError(ValueError):
    """Signal malformed or internally inconsistent benchmark evidence."""


def reject(message: str) -> None:
    """Raise a stable benchmark validation error."""
    raise BenchmarkValidationError(message)


def object_value(value: Any, path: str) -> Mapping[str, Any]:
    """Return a mapping or reject a schema-shape mismatch."""
    if not isinstance(value, Mapping):
        reject(f"{path} must be an object")
    return value


def array_value(value: Any, path: str) -> list[Any]:
    """Return a list or reject a schema-shape mismatch."""
    if not isinstance(value, list):
        reject(f"{path} must be an array")
    return value


def text_value(value: Any, path: str) -> str:
    """Return stripped non-empty text or reject it."""
    if not isinstance(value, str) or not value.strip():
        reject(f"{path} must be non-empty text")
    return value.strip()


def bool_value(value: Any, path: str) -> bool:
    """Return an actual Boolean, excluding integer lookalikes."""
    if not isinstance(value, bool):
        reject(f"{path} must be boolean")
    return value


def count_value(value: Any, path: str, *, positive: bool = False) -> int:
    """Return a non-negative or positive integer count."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        reject(f"{path} must be a non-negative integer")
    if positive and value == 0:
        reject(f"{path} must be positive")
    return value


def rate_value(value: Any, path: str) -> float:
    """Return a finite rate in the closed unit interval."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        reject(f"{path} must be a number between 0 and 1")
    result = float(value)
    if not math.isfinite(result) or not 0.0 <= result <= 1.0:
        reject(f"{path} must be a finite number between 0 and 1")
    return result


def unique_text(value: Any, path: str, seen: set[str]) -> str:
    """Return a unique non-empty identifier within a caller-owned set."""
    result = text_value(value, path)
    if result in seen:
        reject(f"{path} duplicates {result!r}")
    seen.add(result)
    return result


def commit_sha_value(value: Any, path: str, *, required: bool) -> str | None:
    """Return one lowercase full commit SHA or reject missing/malformed evidence."""
    if value is None and not required:
        return None
    result = text_value(value, path)
    if not COMMIT_SHA_RE.fullmatch(result):
        reject(f"{path} must be a 40-character lowercase commit SHA")
    return result


def validate_finding(
    raw_value: Any,
    path: str,
    seen: set[str],
    gold_ids: set[str],
    head_match: bool,
) -> dict[str, Any]:
    """Validate one reviewer-emitted finding and its evidence attributes."""
    value = object_value(raw_value, path)
    finding_id = unique_text(value.get("finding_id"), f"{path}.finding_id", seen)
    gold_id = value.get("gold_finding_id")
    if gold_id is not None:
        gold_id = text_value(gold_id, f"{path}.gold_finding_id")
        if not head_match or gold_id not in gold_ids:
            reject(f"{path}.gold_finding_id must reference current-head gold evidence")
    severity = text_value(value.get("severity"), f"{path}.severity").casefold()
    if severity not in VALID_SEVERITIES:
        reject(f"{path}.severity is invalid")
    return {
        "finding_id": finding_id,
        "gold_finding_id": gold_id,
        "severity": severity,
        "actionable": bool_value(value.get("actionable"), f"{path}.actionable"),
        "source_backed": bool_value(
            value.get("source_backed"), f"{path}.source_backed"
        ),
        "line_anchored": bool_value(
            value.get("line_anchored"), f"{path}.line_anchored"
        ),
        "has_fix_direction": bool_value(
            value.get("has_fix_direction"), f"{path}.has_fix_direction"
        ),
        "has_regression_test_direction": bool_value(
            value.get("has_regression_test_direction"),
            f"{path}.has_regression_test_direction",
        ),
    }


def validate_reviewer(
    raw_value: Any,
    path: str,
    gold_ids: set[str],
    head_match: bool,
    expected_head_sha: str | None,
) -> dict[str, Any]:
    """Validate one reviewer's attempts, blockers, duplicates, and findings."""
    value = object_value(raw_value, path)
    fields = {
        name: count_value(value.get(name), f"{path}.{name}")
        for name in (
            "triggered_attempts",
            "completed_attempts",
            "rate_limited_attempts",
            "infrastructure_only_reviews",
            "duplicate_reviews",
        )
    }
    triggered = fields["triggered_attempts"]
    completed = fields["completed_attempts"]
    limited = fields["rate_limited_attempts"]
    if completed + limited > triggered:
        reject(f"{path} completed plus rate-limited attempts exceed triggered attempts")
    if fields["infrastructure_only_reviews"] > completed:
        reject(f"{path}.infrastructure_only_reviews exceeds completed_attempts")
    if fields["duplicate_reviews"] > completed:
        reject(f"{path}.duplicate_reviews exceeds completed_attempts")
    reviewed_head_sha = commit_sha_value(
        value.get("reviewed_head_sha"),
        f"{path}.reviewed_head_sha",
        required=expected_head_sha is not None,
    )
    if expected_head_sha is not None and reviewed_head_sha != expected_head_sha:
        reject(f"{path}.reviewed_head_sha must equal the case head_sha")
    seen: set[str] = set()
    fields["findings"] = [
        validate_finding(item, f"{path}.findings[{index}]", seen, gold_ids, head_match)
        for index, item in enumerate(array_value(value.get("findings"), f"{path}.findings"))
    ]
    if fields["findings"] and completed == 0:
        reject(f"{path}.findings require at least one completed review attempt")
    fields["reviewed_head_sha"] = reviewed_head_sha
    return fields


def validate_benchmark(raw_value: Any) -> dict[str, Any]:
    """Validate and normalize the benchmark schema without external packages."""
    value = object_value(raw_value, "benchmark")
    if value.get("schema_version") != "1.0":
        reject("schema_version must equal '1.0'")
    benchmark_id = text_value(value.get("benchmark_id"), "benchmark_id")
    mode = text_value(value.get("evaluation_mode"), "evaluation_mode").casefold()
    if mode not in VALID_MODES:
        reject("evaluation_mode is invalid")
    limitations = [
        text_value(item, f"limitations[{index}]")
        for index, item in enumerate(array_value(value.get("limitations"), "limitations"))
    ]
    if not limitations:
        reject("limitations must not be empty")
    policy_value = object_value(value.get("parity_policy"), "parity_policy")
    policy = {
        "candidate_reviewer": text_value(
            policy_value.get("candidate_reviewer"), "parity_policy.candidate_reviewer"
        ).casefold(),
        "reference_reviewer": text_value(
            policy_value.get("reference_reviewer"), "parity_policy.reference_reviewer"
        ).casefold(),
        "minimum_head_matched_cases": count_value(
            policy_value.get("minimum_head_matched_cases"),
            "parity_policy.minimum_head_matched_cases",
            positive=True,
        ),
        "minimum_gold_findings": count_value(
            policy_value.get("minimum_gold_findings"),
            "parity_policy.minimum_gold_findings",
            positive=True,
        ),
        "non_inferiority_margin": rate_value(
            policy_value.get("non_inferiority_margin"),
            "parity_policy.non_inferiority_margin",
        ),
        "required_critical_high_recall": rate_value(
            policy_value.get("required_critical_high_recall"),
            "parity_policy.required_critical_high_recall",
        ),
    }
    if policy["candidate_reviewer"] == policy["reference_reviewer"]:
        reject("candidate and reference reviewers must differ")

    cases: list[dict[str, Any]] = []
    seen_cases: set[str] = set()
    for case_index, raw_case in enumerate(array_value(value.get("cases"), "cases")):
        path = f"cases[{case_index}]"
        case = object_value(raw_case, path)
        case_id = unique_text(case.get("case_id"), f"{path}.case_id", seen_cases)
        repository = text_value(case.get("repository"), f"{path}.repository")
        if not REPOSITORY_RE.fullmatch(repository):
            reject(f"{path}.repository must use owner/name")
        head_match = bool_value(case.get("head_match"), f"{path}.head_match")
        if mode == "head_matched_gold" and not head_match:
            reject(f"{path}.head_match must be true in head_matched_gold mode")
        base_sha = commit_sha_value(
            case.get("base_sha"), f"{path}.base_sha", required=head_match
        )
        head_sha = commit_sha_value(
            case.get("head_sha"), f"{path}.head_sha", required=head_match
        )
        bucket = text_value(
            case.get("diff_size_bucket"), f"{path}.diff_size_bucket"
        ).casefold()
        if bucket not in VALID_BUCKETS:
            reject(f"{path}.diff_size_bucket is invalid")
        gold_seen: set[str] = set()
        gold_findings: list[dict[str, str]] = []
        for gold_index, raw_gold in enumerate(
            array_value(case.get("gold_findings"), f"{path}.gold_findings")
        ):
            gold_path = f"{path}.gold_findings[{gold_index}]"
            gold = object_value(raw_gold, gold_path)
            severity = text_value(
                gold.get("severity"), f"{gold_path}.severity"
            ).casefold()
            if severity not in VALID_SEVERITIES:
                reject(f"{gold_path}.severity is invalid")
            gold_findings.append(
                {
                    "finding_id": unique_text(
                        gold.get("finding_id"), f"{gold_path}.finding_id", gold_seen
                    ),
                    "severity": severity,
                }
            )
        if gold_findings and not head_match:
            reject(f"{path}.gold_findings require head_match=true")
        reviewers_value = object_value(case.get("reviewers"), f"{path}.reviewers")
        if not reviewers_value:
            reject(f"{path}.reviewers must not be empty")
        reviewers: dict[str, dict[str, Any]] = {}
        reviewer_names: set[str] = set()
        for name, reviewer in reviewers_value.items():
            normalized_name = text_value(name, f"{path}.reviewer").casefold()
            if normalized_name in reviewer_names:
                reject(f"{path}.reviewer name duplicates {normalized_name!r}")
            reviewer_names.add(normalized_name)
            reviewers[normalized_name] = validate_reviewer(
                reviewer,
                f"{path}.reviewers.{name}",
                gold_seen,
                head_match,
                head_sha if head_match else None,
            )
        cases.append(
            {
                "case_id": case_id,
                "repository": repository,
                "pull_request_number": count_value(
                    case.get("pull_request_number"),
                    f"{path}.pull_request_number",
                    positive=True,
                ),
                "head_match": head_match,
                "base_sha": base_sha,
                "head_sha": head_sha,
                "diff_size_bucket": bucket,
                "primary_language": text_value(
                    case.get("primary_language"), f"{path}.primary_language"
                ).casefold(),
                "gold_findings": gold_findings,
                "reviewers": reviewers,
            }
        )
    if not cases:
        reject("cases must not be empty")
    return {
        "schema_version": "1.0",
        "benchmark_id": benchmark_id,
        "evaluation_mode": mode,
        "limitations": limitations,
        "parity_policy": policy,
        "cases": cases,
    }


def ratio(numerator: int, denominator: int) -> float | None:
    """Return a six-decimal ratio or ``None`` for an empty denominator."""
    return None if denominator == 0 else round(numerator / denominator, 6)


def wilson(successes: int, trials: int) -> list[float] | None:
    """Return a 95% Wilson binomial interval or ``None`` for no trials."""
    if trials == 0:
        return None
    if successes < 0 or successes > trials:
        raise ValueError("successes must be between zero and trials")
    z = 1.959963984540054
    proportion = successes / trials
    denominator = 1.0 + z * z / trials
    center = (proportion + z * z / (2.0 * trials)) / denominator
    margin = z * math.sqrt(
        proportion * (1.0 - proportion) / trials + z * z / (4.0 * trials * trials)
    ) / denominator
    return [round(max(0.0, center - margin), 6), round(min(1.0, center + margin), 6)]


def score_reviewer(name: str, benchmark: Mapping[str, Any]) -> dict[str, Any]:
    """Aggregate operational metrics and justified head-matched defect metrics."""
    totals = {
        "triggered_attempts": 0,
        "completed_attempts": 0,
        "rate_limited_attempts": 0,
        "infrastructure_only_reviews": 0,
        "duplicate_reviews": 0,
    }
    findings: list[dict[str, Any]] = []
    gold: dict[tuple[str, str], str] = {}
    case_count = 0
    actionable_cases = 0
    for case in benchmark["cases"]:
        for item in case["gold_findings"]:
            gold[(case["case_id"], item["finding_id"])] = item["severity"]
        reviewer = case["reviewers"].get(name)
        if reviewer is None:
            continue
        case_count += 1
        for field in totals:
            totals[field] += reviewer[field]
        case_findings = [item for item in reviewer["findings"] if item["actionable"]]
        actionable_cases += int(bool(case_findings))
        for item in case_findings:
            findings.append({**item, "case_id": case["case_id"]})
    actionable = len(findings)
    completed = totals["completed_attempts"]
    result = {
        "reviewer": name,
        "case_count": case_count,
        **totals,
        "availability_rate": ratio(totals["completed_attempts"], totals["triggered_attempts"]),
        "availability_interval_95": wilson(
            totals["completed_attempts"], totals["triggered_attempts"]
        ),
        "rate_limited_rate": ratio(
            totals["rate_limited_attempts"], totals["triggered_attempts"]
        ),
        "infrastructure_only_review_rate": ratio(
            totals["infrastructure_only_reviews"], completed
        ),
        "duplicate_review_rate": ratio(totals["duplicate_reviews"], completed),
        "actionable_findings": actionable,
        "actionable_findings_per_completed_review": ratio(actionable, completed),
        "actionable_case_rate": ratio(actionable_cases, case_count),
        "source_backed_rate": ratio(
            sum(item["source_backed"] for item in findings), actionable
        ),
        "line_anchored_rate": ratio(
            sum(item["line_anchored"] for item in findings), actionable
        ),
        "fix_direction_rate": ratio(
            sum(item["has_fix_direction"] for item in findings), actionable
        ),
        "regression_test_direction_rate": ratio(
            sum(item["has_regression_test_direction"] for item in findings), actionable
        ),
        "defect_metrics": None,
    }
    if benchmark["evaluation_mode"] != "head_matched_gold":
        return result
    matched: set[tuple[str, str]] = set()
    true_positive = 0
    false_positive = 0
    for finding in findings:
        gold_id = finding["gold_finding_id"]
        key = (finding["case_id"], gold_id) if gold_id is not None else None
        if key is None or key in matched:
            false_positive += 1
        else:
            matched.add(key)
            true_positive += 1
    false_negative = len(gold) - true_positive
    precision = ratio(true_positive, true_positive + false_positive)
    recall = ratio(true_positive, true_positive + false_negative)
    f1 = (
        None
        if precision is None or recall is None or precision + recall == 0
        else round(2 * precision * recall / (precision + recall), 6)
    )
    high_gold = {key for key, severity in gold.items() if severity in {"critical", "high"}}
    result["defect_metrics"] = {
        "gold_findings": len(gold),
        "true_positives": true_positive,
        "false_positives": false_positive,
        "false_negatives": false_negative,
        "precision": precision,
        "precision_interval_95": wilson(true_positive, true_positive + false_positive),
        "recall": recall,
        "recall_interval_95": wilson(true_positive, true_positive + false_negative),
        "f1_score": f1,
        "critical_high_recall": ratio(len(high_gold & matched), len(high_gold)),
    }
    return result


def parity_gate(
    benchmark: Mapping[str, Any], scores: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    """Evaluate reference-relative parity only with sufficient expert gold data."""
    policy = benchmark["parity_policy"]
    candidate_name = policy["candidate_reviewer"]
    reference_name = policy["reference_reviewer"]
    case_count = sum(case["head_match"] for case in benchmark["cases"])
    gold_count = sum(len(case["gold_findings"]) for case in benchmark["cases"])
    reasons: list[str] = []
    if benchmark["evaluation_mode"] != "head_matched_gold":
        reasons.append("benchmark is not head_matched_gold")
    if case_count < policy["minimum_head_matched_cases"]:
        reasons.append("head-matched case count is below minimum")
    if gold_count < policy["minimum_gold_findings"]:
        reasons.append("gold finding count is below minimum")
    candidate = scores.get(candidate_name)
    reference = scores.get(reference_name)
    if candidate is None or reference is None:
        reasons.append("candidate or reference reviewer is absent")
    elif candidate["defect_metrics"] is None or reference["defect_metrics"] is None:
        reasons.append("candidate or reference lacks defect metrics")
    if reasons:
        return {"status": "INSUFFICIENT_EVIDENCE", "reasons": reasons}
    candidate_metrics = candidate["defect_metrics"]
    reference_metrics = reference["defect_metrics"]
    assert candidate_metrics is not None and reference_metrics is not None
    candidate_precision_interval = candidate_metrics["precision_interval_95"]
    candidate_recall_interval = candidate_metrics["recall_interval_95"]
    reference_precision = reference_metrics["precision"]
    reference_recall = reference_metrics["recall"]
    if (
        candidate_precision_interval is None
        or candidate_recall_interval is None
        or reference_precision is None
        or reference_recall is None
    ):
        return {
            "status": "INSUFFICIENT_EVIDENCE",
            "reasons": [
                "candidate or reference precision or recall denominator is zero"
            ],
        }
    margin = policy["non_inferiority_margin"]
    precision_pass = candidate_precision_interval[0] >= reference_precision - margin
    recall_pass = candidate_recall_interval[0] >= reference_recall - margin
    high_recall = candidate_metrics["critical_high_recall"]
    high_pass = high_recall is not None and high_recall >= policy["required_critical_high_recall"]
    return {
        "status": "PASS" if precision_pass and recall_pass and high_pass else "FAIL",
        "method": "Wilson-lower-bound non-inferiority",
        "precision_pass": precision_pass,
        "recall_pass": recall_pass,
        "critical_high_pass": high_pass,
        "reasons": [],
    }


def score_benchmark(raw_value: Any) -> dict[str, Any]:
    """Return deterministic operational, defect, and parity metrics."""
    benchmark = validate_benchmark(raw_value)
    names = sorted(
        {name for case in benchmark["cases"] for name in case["reviewers"]}
    )
    scores = {name: score_reviewer(name, benchmark) for name in names}
    return {
        "schema_version": "1.0",
        "benchmark_id": benchmark["benchmark_id"],
        "evaluation_mode": benchmark["evaluation_mode"],
        "case_count": len(benchmark["cases"]),
        "head_matched_case_count": sum(case["head_match"] for case in benchmark["cases"]),
        "gold_finding_count": sum(
            len(case["gold_findings"]) for case in benchmark["cases"]
        ),
        "reviewers": scores,
        "parity_gate": parity_gate(benchmark, scores),
        "limitations": benchmark["limitations"],
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise Markdown report for CI and doctoring."""
    lines = [
        f"# OpenCode review quality — `{report['benchmark_id']}`",
        "",
        f"- Mode: `{report['evaluation_mode']}`",
        f"- Cases: {report['case_count']}",
        f"- Parity gate: **{report['parity_gate']['status']}**",
        "",
        "| Reviewer | Completed / triggered | Availability | Actionable / completed | Infrastructure-only | Duplicate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for name, score in sorted(report["reviewers"].items()):
        values = [
            score["availability_rate"],
            score["actionable_findings_per_completed_review"],
            score["infrastructure_only_review_rate"],
            score["duplicate_review_rate"],
        ]
        formatted = ["n/a" if value is None else f"{value:.3f}" for value in values]
        lines.append(
            f"| {name} | {score['completed_attempts']} / {score['triggered_attempts']} | "
            f"{formatted[0]} | {formatted[1]} | {formatted[2]} | {formatted[3]} |"
        )
    if report["parity_gate"]["status"] == "INSUFFICIENT_EVIDENCE":
        lines.extend(
            [
                "",
                "Precision, recall, and CodeRabbit parity are **not inferable** from this evidence.",
            ]
        )
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"])
    return "\n".join(lines) + "\n"


def load_json(path: Path) -> Any:
    """Load one UTF-8 JSON document with stable errors."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        reject(f"cannot load benchmark: {error}")


def write_text(path: Path, content: str) -> None:
    """Atomically replace an output file after creating its parent."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the scorer CLI and return stable gate-oriented statuses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--json-output", type=Path)
    parser.add_argument("--markdown-output", type=Path)
    parser.add_argument("--fail-on-parity-regression", action="store_true")
    parser.add_argument("--require-parity-evidence", action="store_true")
    arguments = parser.parse_args(argv)
    try:
        report = score_benchmark(load_json(arguments.input))
    except BenchmarkValidationError as error:
        print(f"review-quality benchmark rejected: {error}", file=sys.stderr)
        return 2
    json_text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if arguments.json_output:
        write_text(arguments.json_output, json_text)
    else:
        sys.stdout.write(json_text)
    if arguments.markdown_output:
        write_text(arguments.markdown_output, render_markdown(report))
    status = report["parity_gate"]["status"]
    if arguments.require_parity_evidence and status == "INSUFFICIENT_EVIDENCE":
        return 3
    return int(arguments.fail_on_parity_regression and status == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
