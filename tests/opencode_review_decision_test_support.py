"""Shared fixtures for OpenCode decision-envelope tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/ci/opencode_review_decision.py"


def load_module() -> ModuleType:
    """Load the exact decision module without package import side effects."""
    spec = importlib.util.spec_from_file_location("opencode_review_decision", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


decision = load_module()


def finding(
    identifier: str = "finding_001",
    *,
    severity: str = "high",
    blocking: bool = True,
) -> dict[str, Any]:
    """Build one complete semantic source finding."""
    return {
        "finding_id": identifier,
        "defect_class": "correctness",
        "severity": severity,
        "blocking": blocking,
        "path": "scripts/ci/example.py",
        "line": 12,
        "trigger": "The input contains a duplicate exact-head identity.",
        "impact": "The benchmark counts one pull request twice.",
        "root_cause": "The identity set is not checked before aggregation.",
        "fix_direction": "Reject duplicate repository, PR, and head tuples.",
        "regression_target": "Add a duplicate exact-head fixture.",
    }


def check(
    name: str = "CI",
    *,
    state: str = "success",
    required: bool = True,
    head_sha: str | None = None,
) -> dict[str, Any]:
    """Build one exact-head check evidence record."""
    return {
        "name": name,
        "state": state,
        "required": required,
        "head_sha": head_sha or "b" * 40,
    }


def envelope(
    *,
    semantic_status: str = "complete",
    findings: list[dict[str, Any]] | None = None,
    coverage_state: str = "success",
    approval_state: str = "success",
    protection_state: str = "success",
    checks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one decision input with all evidence bound to one immutable head."""
    complete = semantic_status == "complete"
    return {
        "schema_version": "1.0",
        "decision_id": "decision_001",
        "quality_policy_version": "opencode-review-quality-v1",
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 42,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "semantic_review": {
            "status": semantic_status,
            "reviewed_head_sha": "b" * 40 if complete else None,
            "findings": findings if findings is not None else [],
        },
        "merge_evidence": {
            "evidence_head_sha": "b" * 40,
            "coverage_state": coverage_state,
            "independent_approval_state": approval_state,
            "branch_protection_state": protection_state,
            "required_checks": checks if checks is not None else [check()],
        },
    }
