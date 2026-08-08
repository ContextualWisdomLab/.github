"""Tests for the empirical automated-review quality scorer."""

from __future__ import annotations

import copy
import importlib.util
import json
import runpy
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/opencode_review_quality_score.py"
PILOT_PATH = ROOT / "benchmarks/opencode_review/pilot_baseline_v1.json"
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40


def load_module() -> ModuleType:
    """Load the exact repository module without package side effects."""
    spec = importlib.util.spec_from_file_location("opencode_review_quality_score", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = load_module()


def finding(identifier: str, gold_id: str | None = None, actionable: bool = True) -> dict[str, Any]:
    """Build one fully evidenced finding fixture."""
    return {
        "finding_id": identifier,
        "gold_finding_id": gold_id,
        "severity": "high",
        "actionable": actionable,
        "source_backed": True,
        "line_anchored": True,
        "has_fix_direction": True,
        "has_regression_test_direction": True,
    }


def reviewer(
    findings: list[dict[str, Any]] | None = None,
    reviewed_head_sha: str | None = None,
) -> dict[str, Any]:
    """Build one successful reviewer-run fixture."""
    value = {
        "triggered_attempts": 1,
        "completed_attempts": 1,
        "rate_limited_attempts": 0,
        "infrastructure_only_reviews": 0,
        "duplicate_reviews": 0,
        "findings": findings or [],
    }
    if reviewed_head_sha is not None:
        value["reviewed_head_sha"] = reviewed_head_sha
    return value


def benchmark(mode: str = "historical_lifecycle", count: int = 1) -> dict[str, Any]:
    """Build a valid benchmark in lifecycle or head-matched mode."""
    value: dict[str, Any] = {
        "schema_version": "1.0",
        "benchmark_id": "fixture",
        "evaluation_mode": mode,
        "limitations": ["Synthetic scorer contract fixture."],
        "parity_policy": {
            "candidate_reviewer": "opencode",
            "reference_reviewer": "coderabbit",
            "minimum_head_matched_cases": 50,
            "minimum_gold_findings": 50,
            "non_inferiority_margin": 0.05,
            "required_critical_high_recall": 1.0,
        },
        "cases": [],
    }
    for index in range(count):
        gold_id = f"gold-{index}"
        head_match = mode == "head_matched_gold"
        value["cases"].append(
            {
                "case_id": f"case-{index}",
                "repository": "ContextualWisdomLab/example",
                "pull_request_number": index + 1,
                "head_match": head_match,
                **({"base_sha": BASE_SHA, "head_sha": HEAD_SHA} if head_match else {}),
                "diff_size_bucket": ("small", "medium", "large")[index % 3],
                "primary_language": ("python", "rust", "typescript", "go")[index % 4],
                "gold_findings": ([{"finding_id": gold_id, "severity": "high"}] if head_match else []),
                "reviewers": {
                    "opencode": reviewer(
                        [finding(f"opencode-{index}", gold_id)]
                        if head_match
                        else [finding(f"opencode-{index}")],
                        HEAD_SHA if head_match else None,
                    ),
                    "coderabbit": reviewer(
                        [finding(f"coderabbit-{index}", gold_id)] if head_match else [],
                        HEAD_SHA if head_match else None,
                    ),
                },
            }
        )
    return value


def test_empirical_pilot_exposes_yield_gap_without_claiming_parity() -> None:
    """The purposive pilot must report operational evidence only."""
    report = quality.score_benchmark(json.loads(PILOT_PATH.read_text(encoding="utf-8")))
    assert report["parity_gate"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["head_matched_case_count"] == report["gold_finding_count"] == 0
    opencode = report["reviewers"]["opencode"]
    coderabbit = report["reviewers"]["coderabbit"]
    assert (opencode["completed_attempts"], opencode["actionable_findings"]) == (8, 0)
    assert opencode["infrastructure_only_review_rate"] == 1.0
    assert opencode["duplicate_review_rate"] == 0.625
    assert opencode["source_backed_rate"] is None
    assert (coderabbit["triggered_attempts"], coderabbit["completed_attempts"]) == (4, 3)
    assert coderabbit["availability_rate"] == 0.75
    assert coderabbit["actionable_findings"] == 8
    assert coderabbit["actionable_findings_per_completed_review"] == 2.666667
    assert coderabbit["source_backed_rate"] == coderabbit["line_anchored_rate"] == 1.0


def test_large_perfect_gold_sample_passes_reference_relative_gate() -> None:
    """A 100-case perfect candidate must pass the Wilson lower-bound gate."""
    report = quality.score_benchmark(benchmark("head_matched_gold", 100))
    metrics = report["reviewers"]["opencode"]["defect_metrics"]
    assert metrics["precision"] == metrics["recall"] == metrics["f1_score"] == 1.0
    assert metrics["precision_interval_95"] == [0.963007, 1.0]
    assert report["parity_gate"] == {
        "status": "PASS",
        "method": "Wilson-lower-bound non-inferiority",
        "precision_pass": True,
        "recall_pass": True,
        "critical_high_pass": True,
        "reasons": [],
    }


def test_false_positive_duplicate_and_missed_high_findings_fail_gate() -> None:
    """Duplicate mappings, unmatched comments, and missed highs must be penalized."""
    value = benchmark("head_matched_gold", 100)
    value["cases"][0]["reviewers"]["opencode"]["findings"] += [
        finding("duplicate", "gold-0"),
        finding("unmatched"),
        finding("nit", actionable=False),
    ]
    for case in value["cases"][:10]:
        case["reviewers"]["opencode"]["findings"] = []
    report = quality.score_benchmark(value)
    metrics = report["reviewers"]["opencode"]["defect_metrics"]
    assert metrics["true_positives"] == 90
    assert metrics["false_positives"] == 0
    assert metrics["false_negatives"] == 10
    assert report["parity_gate"]["status"] == "FAIL"
    assert report["parity_gate"]["recall_pass"] is False
    assert report["parity_gate"]["critical_high_pass"] is False


def test_duplicate_and_unmatched_findings_count_as_false_positives() -> None:
    """Only the first actionable match to a gold identifier is a true positive."""
    value = benchmark("head_matched_gold", 100)
    value["cases"][0]["reviewers"]["opencode"]["findings"] += [
        finding("duplicate", "gold-0"),
        finding("unmatched"),
    ]
    metrics = quality.score_benchmark(value)["reviewers"]["opencode"]["defect_metrics"]
    assert (metrics["true_positives"], metrics["false_positives"]) == (100, 2)
    assert metrics["precision"] == 0.980392


def test_head_matched_evidence_requires_exact_matching_shas() -> None:
    """Gold metrics must bind every reviewer to one immutable PR head."""
    value = benchmark("head_matched_gold", 100)
    del value["cases"][0]["base_sha"]
    with pytest.raises(quality.BenchmarkValidationError, match="base_sha"):
        quality.validate_benchmark(value)

    value = benchmark("head_matched_gold", 100)
    value["cases"][0]["head_sha"] = "not-a-sha"
    with pytest.raises(quality.BenchmarkValidationError, match="head_sha"):
        quality.validate_benchmark(value)

    value = benchmark("head_matched_gold", 100)
    value["cases"][0]["reviewers"]["opencode"]["reviewed_head_sha"] = "3" * 40
    with pytest.raises(quality.BenchmarkValidationError, match="reviewed_head_sha"):
        quality.validate_benchmark(value)


def test_reference_zero_denominator_returns_insufficient_evidence() -> None:
    """A reference with no actionable findings must not cause arithmetic failure."""
    value = benchmark("head_matched_gold", 100)
    for case in value["cases"]:
        case["reviewers"]["coderabbit"]["findings"] = []
    assert quality.score_benchmark(value)["parity_gate"] == {
        "status": "INSUFFICIENT_EVIDENCE",
        "reasons": ["candidate or reference precision or recall denominator is zero"],
    }


def test_reviewer_names_and_completed_review_evidence_fail_closed() -> None:
    """Case-fold collisions and findings without a completed review are invalid."""
    value = benchmark()
    value["cases"][0]["reviewers"]["OpenCode"] = copy.deepcopy(
        value["cases"][0]["reviewers"]["opencode"]
    )
    with pytest.raises(quality.BenchmarkValidationError, match="reviewer name duplicates"):
        quality.validate_benchmark(value)

    value = benchmark()
    value["cases"][0]["reviewers"]["opencode"]["completed_attempts"] = 0
    with pytest.raises(quality.BenchmarkValidationError, match="findings require"):
        quality.validate_benchmark(value)


def test_parity_refuses_small_missing_or_zero_denominator_evidence() -> None:
    """Parity must remain unavailable for underpowered or missing-reviewer data."""
    report = quality.score_benchmark(benchmark("head_matched_gold", 2))
    assert report["parity_gate"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert len(report["parity_gate"]["reasons"]) == 2

    value = benchmark("head_matched_gold", 100)
    for case in value["cases"]:
        del case["reviewers"]["coderabbit"]
    assert quality.score_benchmark(value)["parity_gate"]["reasons"] == [
        "candidate or reference reviewer is absent"
    ]

    value = benchmark("head_matched_gold", 100)
    for case in value["cases"]:
        case["reviewers"]["opencode"]["findings"] = []
        case["reviewers"]["coderabbit"]["findings"] = []
    assert quality.score_benchmark(value)["parity_gate"]["reasons"] == [
        "candidate or reference precision or recall denominator is zero"
    ]


def test_sparse_reviewer_cases_and_empty_ratios_are_supported() -> None:
    """A reviewer may be absent from one lifecycle case without corrupting totals."""
    value = benchmark(count=2)
    del value["cases"][1]["reviewers"]["opencode"]
    value["cases"][0]["reviewers"]["coderabbit"] = reviewer()
    report = quality.score_benchmark(value)
    assert report["reviewers"]["opencode"]["case_count"] == 1
    assert report["reviewers"]["coderabbit"]["actionable_findings_per_completed_review"] == 0.0
    assert quality.ratio(1, 0) is None
    assert quality.wilson(0, 0) is None
    with pytest.raises(ValueError, match="between zero and trials"):
        quality.wilson(2, 1)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: [], "benchmark must be an object"),
        (lambda value: {**value, "schema_version": "2"}, "schema_version"),
        (lambda value: {**value, "benchmark_id": ""}, "benchmark_id"),
        (lambda value: {**value, "evaluation_mode": "other"}, "evaluation_mode"),
        (lambda value: {**value, "limitations": {}}, "limitations must be an array"),
        (lambda value: {**value, "limitations": []}, "limitations must not be empty"),
        (lambda value: {**value, "parity_policy": []}, "parity_policy must be an object"),
        (lambda value: _set(value, ["parity_policy", "reference_reviewer"], "opencode"), "must differ"),
        (lambda value: _set(value, ["parity_policy", "minimum_head_matched_cases"], 0), "must be positive"),
        (lambda value: _set(value, ["parity_policy", "minimum_gold_findings"], True), "non-negative integer"),
        (lambda value: _set(value, ["parity_policy", "non_inferiority_margin"], "x"), "must be a number"),
        (lambda value: _set(value, ["parity_policy", "required_critical_high_recall"], 2), "finite number"),
        (lambda value: {**value, "cases": []}, "cases must not be empty"),
        (lambda value: _append_duplicate_case(value), "duplicates"),
        (lambda value: _set(value, ["cases", 0, "repository"], "invalid"), "owner/name"),
        (lambda value: _set(value, ["cases", 0, "pull_request_number"], 0), "must be positive"),
        (lambda value: _set(value, ["cases", 0, "head_match"], "false"), "must be boolean"),
        (lambda value: _set(value, ["cases", 0, "diff_size_bucket"], "huge"), "diff_size_bucket"),
        (lambda value: _set(value, ["cases", 0, "primary_language"], ""), "primary_language"),
        (lambda value: _set(value, ["cases", 0, "gold_findings"], {}), "gold_findings must be an array"),
        (lambda value: _set(value, ["cases", 0, "reviewers"], {}), "reviewers must not be empty"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode"], []), "must be an object"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "triggered_attempts"], -1), "non-negative integer"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "rate_limited_attempts"], 1), "exceed triggered"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "infrastructure_only_reviews"], 2), "exceeds completed"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "duplicate_reviews"], 2), "exceeds completed"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "findings"], {}), "findings must be an array"),
        (lambda value: _duplicate_finding(value), "duplicates"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "findings", 0, "severity"], "urgent"), "severity"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "findings", 0, "actionable"], 1), "must be boolean"),
        (lambda value: _set(value, ["cases", 0, "reviewers", "opencode", "findings", 0, "gold_finding_id"], "unknown"), "current-head gold"),
    ],
)
def test_validation_fails_closed(mutate: Any, message: str) -> None:
    """Malformed counts, shapes, identifiers, and evidence links must be rejected."""
    value = benchmark()
    with pytest.raises(quality.BenchmarkValidationError, match=message):
        quality.validate_benchmark(mutate(value))


def _set(value: dict[str, Any], path: list[Any], replacement: Any) -> dict[str, Any]:
    """Mutate and return a nested fixture value."""
    cursor: Any = value
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = replacement
    return value


def _append_duplicate_case(value: dict[str, Any]) -> dict[str, Any]:
    """Append a duplicate case identifier for validation coverage."""
    value["cases"].append(copy.deepcopy(value["cases"][0]))
    return value


def _duplicate_finding(value: dict[str, Any]) -> dict[str, Any]:
    """Append a duplicate finding identifier for validation coverage."""
    items = value["cases"][0]["reviewers"]["opencode"]["findings"]
    items.append(copy.deepcopy(items[0]))
    return value


def test_gold_validation_and_head_match_contracts() -> None:
    """Gold mode must reject stale heads, invalid severities, and duplicate gold IDs."""
    value = benchmark()
    value["cases"][0]["gold_findings"] = [
        {"finding_id": "unmatched-gold", "severity": "high"}
    ]
    with pytest.raises(quality.BenchmarkValidationError, match="head_match=true"):
        quality.validate_benchmark(value)
    value = benchmark("head_matched_gold")
    value["cases"][0]["head_match"] = False
    with pytest.raises(quality.BenchmarkValidationError, match="head_match"):
        quality.validate_benchmark(value)
    value = benchmark("head_matched_gold")
    value["cases"][0]["gold_findings"][0]["severity"] = "urgent"
    with pytest.raises(quality.BenchmarkValidationError, match="severity"):
        quality.validate_benchmark(value)
    value = benchmark("head_matched_gold")
    value["cases"][0]["gold_findings"].append(copy.deepcopy(value["cases"][0]["gold_findings"][0]))
    with pytest.raises(quality.BenchmarkValidationError, match="duplicates"):
        quality.validate_benchmark(value)


def test_markdown_and_cli_outputs_are_deterministic(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Reports, atomic writes, statuses, input errors, and module entrypoint are stable."""
    lifecycle = benchmark()
    report = quality.score_benchmark(lifecycle)
    markdown = quality.render_markdown(report)
    assert "Precision, recall, and CodeRabbit parity are **not inferable**" in markdown
    assert "| opencode | 1 / 1 | 1.000 | 1.000 | 0.000 | 0.000 |" in markdown

    assert "not inferable" not in quality.render_markdown(quality.score_benchmark(benchmark("head_matched_gold", 100)))

    input_path = tmp_path / "input.json"
    input_path.write_text(json.dumps(lifecycle), encoding="utf-8")
    json_path = tmp_path / "out/report.json"
    md_path = tmp_path / "out/report.md"
    assert quality.main(["--input", str(input_path), "--json-output", str(json_path), "--markdown-output", str(md_path)]) == 0
    assert json.loads(json_path.read_text(encoding="utf-8"))["parity_gate"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert not (json_path.parent / ".report.json.tmp").exists()
    assert quality.main(["--input", str(input_path), "--require-parity-evidence"]) == 3
    assert '"INSUFFICIENT_EVIDENCE"' in capsys.readouterr().out

    passing = tmp_path / "pass.json"
    passing.write_text(json.dumps(benchmark("head_matched_gold", 100)), encoding="utf-8")
    assert quality.main(["--input", str(passing), "--fail-on-parity-regression"]) == 0
    failing_value = benchmark("head_matched_gold", 100)
    for case in failing_value["cases"][:10]:
        case["reviewers"]["opencode"]["findings"] = []
    failing = tmp_path / "fail.json"
    failing.write_text(json.dumps(failing_value), encoding="utf-8")
    assert quality.main(["--input", str(failing), "--fail-on-parity-regression"]) == 1

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert quality.main(["--input", str(invalid)]) == 2
    assert "benchmark rejected" in capsys.readouterr().err
    with pytest.raises(quality.BenchmarkValidationError, match="cannot load"):
        quality.load_json(tmp_path / "missing.json")

    monkeypatch.setattr(sys, "argv", [str(MODULE_PATH), "--input", str(input_path)])
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(MODULE_PATH), run_name="__main__")


def test_all_production_callables_are_documented() -> None:
    """Every locally defined production callable must retain a docstring."""
    missing = [
        name
        for name, value in vars(quality).items()
        if getattr(value, "__module__", None) == quality.__name__
        and callable(value)
        and not getattr(value, "__doc__", None)
    ]
    assert missing == []
