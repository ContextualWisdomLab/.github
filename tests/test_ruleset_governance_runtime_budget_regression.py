"""Regress the owner-plane runtime budget against ambiguous recovery request counts."""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "ci" / "reconcile_ruleset_governance.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ruleset-governance-reconcile.yml"


def load_module():
    """Load the production reconciler from the exact checkout."""

    spec = importlib.util.spec_from_file_location("ruleset_governance_runtime_budget", SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_ambiguous_recovery_budget_counts_every_history_state_read() -> None:
    """Every settlement poll may add one history-state GET and must be budgeted."""

    module = load_module()
    expected_recovery_operations = (
        module.RECOVERY_BLOCKING_OPERATIONS_PER_ATTEMPT
        + (module.AMBIGUOUS_WRITE_SETTLEMENT_POLLS - 1)
        + module.AMBIGUOUS_WRITE_SETTLEMENT_POLLS
    )
    expected_blocking_operations = (
        module.BASE_MUTATION_BLOCKING_OPERATIONS_PER_TARGET
        + module.AMBIGUOUS_SETTLEMENT_BLOCKING_OPERATIONS_PER_TARGET
        + module.COLLISION_RECOVERY_LIMIT * expected_recovery_operations
        + module.POST_CONFIRM_BLOCKING_OPERATIONS_PER_TARGET
        + module.FINAL_VERIFY_BLOCKING_OPERATIONS_PER_TARGET
    )
    expected_settlement_seconds = (
        module.AMBIGUOUS_WRITE_SETTLEMENT_WINDOW_SECONDS
        + module.COLLISION_RECOVERY_LIMIT
        * module.AMBIGUOUS_WRITE_SETTLEMENT_WINDOW_SECONDS
    )
    expected_seconds = 2 * (
        expected_blocking_operations * module.API_REQUEST_TIMEOUT_SECONDS
        + expected_settlement_seconds
    )

    assert module.worst_case_apply_seconds(target_count=2) == expected_seconds
    assert expected_seconds == 7_680


def test_workflow_timeout_and_focused_gate_cover_runtime_budget_regression() -> None:
    """The apply job and focused CI must cover the source-derived 128-minute bound."""

    module = load_module()
    workflow = WORKFLOW.read_text(encoding="utf-8")
    regression = "tests/test_ruleset_governance_runtime_budget_regression.py"
    assert workflow.count(f'"{regression}"') >= 2
    assert regression in workflow.split("python -m coverage run", 1)[1]

    apply_section = workflow.split("  apply:\n", 1)[1]
    timeout_match = re.search(r"timeout-minutes:\s*(\d+)", apply_section)
    assert timeout_match is not None
    configured_minutes = int(timeout_match.group(1))
    required_minutes = math.ceil(module.worst_case_apply_seconds(target_count=2) / 60)
    assert required_minutes == 128
    assert configured_minutes >= required_minutes
