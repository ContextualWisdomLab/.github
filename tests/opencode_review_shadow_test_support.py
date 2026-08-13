"""Shared fixtures for OpenCode shadow detector-verifier tests."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SHADOW_PATH = ROOT / "scripts/ci/opencode_review_shadow.py"
VERIFY_PATH = ROOT / "scripts/ci/opencode_review_verify.py"
WRAPPER_PATH = ROOT / "scripts/ci/run_opencode_semantic_review_pool.sh"


def load_module(name: str, path: Path) -> ModuleType:
    """Load one exact production module without package import side effects."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


shadow = load_module("opencode_review_shadow", SHADOW_PATH)
verify = load_module("opencode_review_verify", VERIFY_PATH)


def digest_text(value: str) -> str:
    """Return the canonical SHA-256 label used by evidence fixtures."""
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def model(
    descriptor_id: str,
    model_id: str,
    *,
    roles: list[str],
    efforts: list[str] | None = None,
    agent_name: str = "ci-review",
    provider_id: str = "nvidia-nim",
) -> dict[str, Any]:
    """Build one provider-neutral, credential-free OpenCode model descriptor."""
    return {
        "descriptor_id": descriptor_id,
        "provider_id": provider_id,
        "model_id": model_id,
        "agent_name": agent_name,
        "role_codes": roles,
        "reasoning_efforts": efforts or ["low", "medium", "high"],
        "prompt_sha256": digest_text(f"prompt:{descriptor_id}"),
    }


def changed_file(
    path: str = "src/example.py",
    *,
    language: str = "python",
    additions: int = 20,
    deletions: int = 5,
    risk_tags: list[str] | None = None,
) -> dict[str, Any]:
    """Build one exact-head changed-file routing record."""
    return {
        "path": path,
        "primary_language": language,
        "additions": additions,
        "deletions": deletions,
        "risk_tags": risk_tags or [],
    }


def request(
    *,
    files: list[dict[str, Any]] | None = None,
    maximum_detector_attempts: int = 5,
    maximum_recursive_verification_depth: int = 1,
    models: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build one strict shadow-review request and bounded model policy."""
    default_models = [
        model(
            "general_super",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            roles=["general_detector", "correctness_detector"],
        ),
        model(
            "security_ultra",
            "nvidia/nemotron-3-ultra-550b-a55b",
            roles=["security_detector", "workflow_detector"],
        ),
        model(
            "numerical_mistral",
            "mistralai/mistral-large-2-instruct",
            roles=["numerical_detector", "data_model_detector"],
        ),
        model(
            "experience_llama",
            "meta/llama-3.3-70b-instruct",
            roles=["experience_detector", "documentation_detector"],
        ),
        model(
            "verifier_gemma",
            "google/gemma-4-31b-it",
            roles=["verifier", "recursive_verifier"],
            agent_name="ci-review-fallback",
        ),
        model(
            "verifier_deepseek",
            "deepseek-ai/deepseek-v4-pro",
            roles=["verifier", "recursive_verifier"],
            agent_name="ci-review-fallback",
        ),
    ]
    return {
        "schema_version": "1.0",
        "review_request_id": "review_request_001",
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 42,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "diff_sha256": digest_text("diff"),
        "evidence_sha256": digest_text("evidence"),
        "changed_files": files if files is not None else [changed_file()],
        "policy": {
            "shadow_mode": True,
            "publication_enabled": False,
            "maximum_detector_attempts": maximum_detector_attempts,
            "maximum_recursive_verification_depth": maximum_recursive_verification_depth,
            "attempt_timeout_seconds": 7200,
            "model_pool": models if models is not None else default_models,
        },
    }


def source_index() -> list[dict[str, Any]]:
    """Build trusted source-line receipts for one candidate and one connected line."""
    return [
        {
            "path": "src/example.py",
            "line": 12,
            "source_line_sha256": digest_text("if identity in seen:"),
            "relationship": "changed",
        },
        {
            "path": "src/helper.py",
            "line": 4,
            "source_line_sha256": digest_text("return identity"),
            "relationship": "connected",
        },
    ]


def attempt(
    attempt_id: str,
    *,
    phase: str,
    role_code: str,
    model_id: str,
    provider_id: str = "nvidia-nim",
    status: str = "complete",
) -> dict[str, Any]:
    """Build one exact-head detector or verifier attempt receipt."""
    return {
        "attempt_id": attempt_id,
        "phase": phase,
        "role_code": role_code,
        "provider_id": provider_id,
        "model_id": model_id,
        "reviewed_head_sha": "b" * 40,
        "status": status,
        "output_sha256": digest_text(f"output:{attempt_id}"),
    }


def candidate(
    candidate_id: str = "candidate_001",
    *,
    detector_attempt_id: str = "detector_001",
    path: str = "src/example.py",
    line: int = 12,
    source_line_sha256: str | None = None,
    infrastructure_only: bool = False,
    root_cause: str = "The identity set is not checked before aggregation.",
) -> dict[str, Any]:
    """Build one complete normalized detector candidate."""
    return {
        "candidate_id": candidate_id,
        "detector_attempt_id": detector_attempt_id,
        "reviewed_head_sha": "b" * 40,
        "infrastructure_only": infrastructure_only,
        "path": path,
        "line": line,
        "source_line_sha256": source_line_sha256 or digest_text("if identity in seen:"),
        "defect_class": "correctness",
        "severity": "high",
        "blocking": True,
        "trigger": "The input contains a duplicate exact-head identity.",
        "impact": "The benchmark counts one pull request twice.",
        "root_cause": root_cause,
        "fix_direction": "Reject duplicate repository, PR, and head tuples.",
        "regression_target": "Add a duplicate exact-head fixture.",
    }


def verifier_decision(
    candidate_id: str = "candidate_001",
    *,
    verifier_attempt_id: str = "verifier_001",
    outcome: str = "supported",
    source_line_sha256: str | None = None,
) -> dict[str, Any]:
    """Build one normalized independent verifier decision."""
    return {
        "candidate_id": candidate_id,
        "verifier_attempt_id": verifier_attempt_id,
        "outcome": outcome,
        "reason": "Exact source and connected context support the candidate."
        if outcome == "supported"
        else "The candidate is not supported by the exact source.",
        "source_line_sha256": source_line_sha256 or digest_text("if identity in seen:"),
    }


def verification_input(
    *,
    candidates: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    minimum_independent_verifiers: int = 1,
    require_model_diversity: bool = True,
) -> dict[str, Any]:
    """Build one exact-head shadow verification bundle."""
    return {
        "schema_version": "1.0",
        "verification_id": "verification_001",
        "repository": "ContextualWisdomLab/example",
        "pull_request_number": 42,
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "evidence_sha256": digest_text("evidence"),
        "risk_tier": "high",
        "verification_policy": {
            "shadow_mode": True,
            "publication_enabled": False,
            "minimum_independent_verifiers": minimum_independent_verifiers,
            "require_model_diversity": require_model_diversity,
        },
        "source_index": source_index(),
        "detector_attempts": [
            attempt(
                "detector_001",
                phase="detector",
                role_code="general_detector",
                model_id="nvidia/llama-3.3-nemotron-super-49b-v1.5",
            )
        ],
        "verifier_attempts": [
            attempt(
                "verifier_001",
                phase="verifier",
                role_code="verifier",
                model_id="google/gemma-4-31b-it",
            ),
            attempt(
                "verifier_002",
                phase="verifier",
                role_code="recursive_verifier",
                model_id="deepseek-ai/deepseek-v4-pro",
            ),
        ],
        "candidates": candidates if candidates is not None else [candidate()],
        "verifier_decisions": decisions
        if decisions is not None
        else [verifier_decision()],
    }


def write_json(path: Path, value: Any) -> None:
    """Write deterministic UTF-8 JSON for CLI and execution fixtures."""
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )
