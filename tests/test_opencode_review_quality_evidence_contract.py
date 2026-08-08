"""Regression tests for empirical review-evidence integrity."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/opencode_review_quality_score.py"


def load_module() -> ModuleType:
    """Load the exact scorer module without package side effects."""
    spec = importlib.util.spec_from_file_location(
        "opencode_review_quality_evidence_contract", MODULE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = load_module()


def finding(identifier: str, gold_identifier: str) -> dict[str, Any]:
    """Build one source-contract-complete reviewer finding."""
    return {
        "finding_id": identifier,
        "gold_finding_id": gold_identifier,
        "severity": "high",
        "actionable": True,
        "source_backed": True,
        "line_anchored": True,
        "has_fix_direction": True,
        "has_regression_test_direction": True,
    }


def reviewer(identifier: str, gold_identifier: str, head_sha: str) -> dict[str, Any]:
    """Build one completed semantic review fixture bound to the exact case head."""
    return {
        "triggered_attempts": 1,
        "completed_attempts": 1,
        "rate_limited_attempts": 0,
        "infrastructure_only_reviews": 0,
        "duplicate_reviews": 0,
        "reviewed_head_sha": head_sha,
        "findings": [finding(identifier, gold_identifier)],
    }


def benchmark(count: int = 50) -> dict[str, Any]:
    """Build a minimally eligible exact-head expert-gold benchmark."""
    cases: list[dict[str, Any]] = []
    for index in range(count):
        gold_identifier = f"gold-{index}"
        head_sha = f"{index:040x}"
        cases.append(
            {
                "case_id": f"case-{index}",
                "repository": "ContextualWisdomLab/example",
                "pull_request_number": index + 1,
                "head_match": True,
                "base_sha": "a" * 40,
                "head_sha": head_sha,
                "diff_size_bucket": ("small", "medium", "large")[index % 3],
                "primary_language": ("python", "rust", "typescript")[index % 3],
                "gold_findings": [
                    {"finding_id": gold_identifier, "severity": "high"}
                ],
                "reviewers": {
                    "opencode": reviewer(
                        f"opencode-{index}", gold_identifier, head_sha
                    ),
                    "coderabbit": reviewer(
                        f"coderabbit-{index}", gold_identifier, head_sha
                    ),
                },
            }
        )
    return {
        "schema_version": "1.0",
        "benchmark_id": "exact-head-fixture",
        "evaluation_mode": "head_matched_gold",
        "limitations": ["Synthetic evidence-integrity fixture."],
        "parity_policy": {
            "candidate_reviewer": "opencode",
            "reference_reviewer": "coderabbit",
            "minimum_head_matched_cases": 50,
            "minimum_gold_findings": 50,
            "non_inferiority_margin": 0.05,
            "required_critical_high_recall": 1.0,
        },
        "cases": cases,
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update({"unexpected": True}),
        lambda value: value["parity_policy"].update({"unexpected": True}),
        lambda value: value["cases"][0].update({"unexpected": True}),
        lambda value: value["cases"][0]["gold_findings"][0].update(
            {"unexpected": True}
        ),
        lambda value: value["cases"][0]["reviewers"]["opencode"].update(
            {"unexpected": True}
        ),
        lambda value: value["cases"][0]["reviewers"]["opencode"][
            "findings"
        ][0].update({"unexpected": True}),
    ],
)
def test_strict_schema_rejects_unknown_fields(mutate: Any) -> None:
    """Every schema layer must fail closed on unreviewed input fields."""
    value = benchmark()
    mutate(value)
    with pytest.raises(quality.BenchmarkValidationError, match="unknown fields"):
        quality.validate_benchmark(value)


def test_head_matched_cases_require_immutable_base_and_head_shas() -> None:
    """A Boolean assertion alone must not establish exact-head comparability."""
    missing = benchmark()
    del missing["cases"][0]["base_sha"]
    with pytest.raises(quality.BenchmarkValidationError, match="base_sha"):
        quality.validate_benchmark(missing)

    malformed = benchmark()
    malformed["cases"][0]["head_sha"] = "main"
    with pytest.raises(quality.BenchmarkValidationError, match="head_sha"):
        quality.validate_benchmark(malformed)


def test_reviewer_names_must_be_unique_after_normalization() -> None:
    """Case-fold-equivalent reviewer names must not silently overwrite evidence."""
    value = benchmark()
    value["cases"][0]["reviewers"]["OpenCode"] = value["cases"][0][
        "reviewers"
    ]["opencode"]
    with pytest.raises(quality.BenchmarkValidationError, match="reviewer.*duplicates"):
        quality.validate_benchmark(value)


def test_every_exact_head_case_requires_both_compared_reviewers() -> None:
    """Parity must not compare reviewers over different case subsets."""
    value = benchmark()
    del value["cases"][0]["reviewers"]["opencode"]
    with pytest.raises(
        quality.BenchmarkValidationError, match="candidate or reference reviewer"
    ):
        quality.validate_benchmark(value)


def test_lifecycle_missing_candidate_remains_insufficient_evidence() -> None:
    """Lifecycle evidence may be sparse but must never imply reviewer parity."""
    value = benchmark(count=1)
    case = value["cases"][0]
    value["evaluation_mode"] = "historical_lifecycle"
    case["head_match"] = False
    del case["base_sha"]
    del case["head_sha"]
    case["gold_findings"] = []
    del case["reviewers"]["opencode"]
    case["reviewers"]["coderabbit"]["findings"] = []
    report = quality.score_benchmark(value)
    assert report["parity_gate"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert "candidate or reference reviewer is absent" in report["parity_gate"][
        "reasons"
    ]


def test_gold_match_without_source_contract_is_not_a_true_positive() -> None:
    """Mapped but unsupported comments must count as noise and leave a miss."""
    value = benchmark()
    value["cases"][0]["reviewers"]["opencode"]["findings"][0][
        "source_backed"
    ] = False
    metrics = quality.score_benchmark(value)["reviewers"]["opencode"][
        "defect_metrics"
    ]
    assert metrics is not None
    assert (
        metrics["true_positives"],
        metrics["false_positives"],
        metrics["false_negatives"],
    ) == (49, 1, 1)
