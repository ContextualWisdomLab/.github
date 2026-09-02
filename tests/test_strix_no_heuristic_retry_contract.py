"""Contracts removing repository-authored retry/test-time-compute heuristics from Strix."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
GATE = ROOT / "scripts" / "ci" / "strix_quick_gate.sh"


def test_central_strix_does_not_allocate_repository_authored_retry_compute() -> None:
    """The central review path gets one execution; provider failover belongs to the orchestrator."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    forbidden = (
        "STRIX_LLM_MAX_RETRIES:",
        "STRIX_TRANSIENT_RETRY_PER_MODEL:",
        "STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS:",
        "STRIX_GATE_RETRY_BACKOFF_SECONDS",
        "strix_gate_attempt",
        "backoff_seconds=",
        "retrying after ${backoff_seconds}s backoff",
        "reached the retry limit",
    )
    for token in forbidden:
        assert token not in workflow, token

    assert 'bash "$TRUSTED_STRIX_GATE" 2>&1 | tee "$strix_terminal_log"' in workflow
    assert "provider/backend was unavailable" in workflow


def test_strix_gate_has_no_same_model_retry_allocator() -> None:
    """The reusable gate must fail closed instead of allocating another model execution."""
    gate = GATE.read_text(encoding="utf-8")
    forbidden = (
        "STRIX_TRANSIENT_RETRY_PER_MODEL",
        "STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS",
        "run_strix_with_transient_retry()",
        "github_models_rate_limit_should_skip_same_model_retry()",
        "is_transient_same_model_retry_error()",
        "Retrying model '$model'",
    )
    for token in forbidden:
        assert token not in gate, token

    assert 'run_strix_once "$PRIMARY_MODEL" || primary_scan_rc=$?' in gate
