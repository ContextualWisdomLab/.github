"""Fail-first contract for the empirical OpenCode review-quality scorer."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/opencode_review_quality_score.py"
PILOT_PATH = ROOT / "benchmarks/opencode_review/pilot_baseline_v1.json"


def load_quality_module():
    """Load the exact production scorer path required by this contract."""
    specification = importlib.util.spec_from_file_location(
        "opencode_review_quality_score", MODULE_PATH
    )
    assert specification is not None
    assert specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def test_pilot_baseline_exposes_yield_gap_without_false_parity() -> None:
    """Historical lifecycle evidence must not be mislabeled as precision or recall."""
    quality = load_quality_module()
    report = quality.score_benchmark(json.loads(PILOT_PATH.read_text(encoding="utf-8")))

    assert report["parity_gate"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert report["head_matched_case_count"] == 0
    assert report["gold_finding_count"] == 0
    assert report["reviewers"]["opencode"]["completed_attempts"] == 8
    assert report["reviewers"]["opencode"]["actionable_findings"] == 0
    assert report["reviewers"]["opencode"]["infrastructure_only_review_rate"] == 1.0
    assert report["reviewers"]["opencode"]["duplicate_review_rate"] == 0.625
    assert report["reviewers"]["coderabbit"]["completed_attempts"] == 3
    assert report["reviewers"]["coderabbit"]["actionable_findings"] == 8
    assert report["reviewers"]["coderabbit"]["availability_rate"] == 0.75
