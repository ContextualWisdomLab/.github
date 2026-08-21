"""Event-to-mode contract for the organization-required Strix workflow.

CWL runs both GitHub Flow (main/master) and Git Flow (develop) without a
consistent RC-tag or prerelease convention. Official Strix CLI modes are only
``quick``, ``standard``, and ``deep``. This module pins the dual-flow mapping
and keeps Deep unwired on this privileged file so a branch-selected
``workflow_dispatch`` cannot mint OIDC tokens or publish a fake ``strix``
status.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "strix.yml"
STRIX_GATE = REPO_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
QUALITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"

SCAN_MODE_EXPRESSION = (
    "STRIX_SCAN_MODE: ${{ github.event_name == 'schedule' && 'standard' || "
    "github.event_name == 'push' && (github.ref == 'refs/heads/main' || "
    "github.ref == 'refs/heads/master') && 'standard' || 'quick' }}"
)


def _workflow() -> str:
    """Return the current central Strix workflow text."""
    return STRIX_WORKFLOW.read_text(encoding="utf-8")


def _trigger_block(workflow: str) -> str:
    """Return the ``on:`` block before concurrency."""
    return workflow.split("concurrency:", 1)[0]


def _strix_job_header(workflow: str) -> str:
    """Return the ``strix`` job header before its first step."""
    job = workflow.split("  strix:\n", 1)[1]
    return job.split("    steps:", 1)[0]


def _run_strix_step(workflow: str) -> str:
    """Return the official-mode scan step without loading workflow YAML tags."""
    marker = "      - name: Run Strix\n"
    start = workflow.index(marker)
    end = workflow.index("\n      - name:", start + len(marker))
    return workflow[start:end]


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace."""
    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) {{\n.*?^}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _require_safe_scan_mode_rc(scan_mode: str) -> int:
    """Execute the production allowlist against one candidate mode."""
    function_source = _function_block(
        STRIX_GATE.read_text(encoding="utf-8"),
        "require_safe_scan_mode",
    )
    script = "\n".join(
        (
            "set -euo pipefail",
            function_source,
            'require_safe_scan_mode "$1"',
        )
    )
    completed = subprocess.run(
        ["bash", "-c", script, "strix-scan-mode", scan_mode],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode not in {0, 2}:
        raise AssertionError(completed.stderr)
    return completed.returncode


def test_quality_trigger_includes_scan_mode_contract_paths() -> None:
    """Keep mapping and doctoring changes inside the exact-head quality job."""
    workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")
    trigger = workflow[: workflow.index("\njobs:")]

    assert "docs/doctoring/strix-scan-mode-dual-flow.md" in trigger
    assert "tests/test_strix_scan_mode_policy.py" in trigger
    assert '      - ".github/workflows/strix.yml"' in trigger
    assert "tests/test_strix_scan_mode_policy.py" in workflow


def test_workflow_pins_official_scan_mode_expression() -> None:
    """The job must set STRIX_SCAN_MODE from event and protected-branch ref."""
    workflow = _workflow()

    assert SCAN_MODE_EXPRESSION in workflow
    assert "client_payload.scan_mode" not in workflow
    assert "github.event.inputs.scan_mode" not in workflow
    assert "          - normal" not in workflow
    assert "|| 'normal'" not in workflow
    assert "|| 'deep'" not in workflow
    assert "&& 'deep'" not in workflow


@pytest.mark.parametrize(
    ("event_name", "ref", "expected"),
    (
        ("pull_request_target", "refs/heads/main", "quick"),
        ("repository_dispatch", "refs/heads/main", "quick"),
        ("push", "refs/heads/develop", "quick"),
        ("push", "refs/heads/main", "standard"),
        ("push", "refs/heads/master", "standard"),
        ("schedule", "refs/heads/develop", "standard"),
        ("schedule", "refs/heads/main", "standard"),
    ),
)
def test_dual_flow_event_maps_to_official_mode(
    event_name: str,
    ref: str,
    expected: str,
) -> None:
    """Mirror the pinned workflow expression for the confirmed dual-flow policy."""
    if event_name == "schedule":
        actual = "standard"
    elif event_name == "push" and ref in {"refs/heads/main", "refs/heads/master"}:
        actual = "standard"
    else:
        actual = "quick"

    assert actual == expected
    assert SCAN_MODE_EXPRESSION in _workflow()
    assert expected in {"quick", "standard"}


def test_repository_dispatch_cannot_inherit_standard_from_default_branch_ref() -> None:
    """``repository_dispatch`` SHA is often main; mode must still stay quick."""
    workflow = _workflow()

    assert "github.event_name == 'push' && (github.ref == 'refs/heads/main'" in workflow
    assert "client_payload.scan_mode" not in workflow
    header = _strix_job_header(workflow)
    assert "repository_dispatch" not in header or "STRIX_SCAN_MODE" in header
    assert "|| 'quick' }}" in header


def test_required_pr_and_quick_paths_keep_standard_timeout_budget() -> None:
    """Deep ceilings must not become the required pull_request_target job."""
    workflow = _workflow()
    header = _strix_job_header(workflow)
    step = _run_strix_step(workflow)

    assert "timeout-minutes: 120" in header
    assert "timeout-minutes: 100" in step
    assert "timeout-minutes: 360" not in header
    assert "timeout-minutes: 340" not in step
    assert "timeout-minutes: 360" not in step
    assert 'process_budget_seconds="5400"' in step
    assert 'total_budget_seconds="5700"' in step
    assert 'process_budget_seconds="14400"' not in step
    assert 'total_budget_seconds="16200"' not in step
    assert "workflow_dispatch" not in step


def test_privileged_strix_workflow_has_no_branch_selected_manual_dispatch() -> None:
    """Manual Deep must not load this privileged YAML from a caller-selected ref."""
    trigger = _trigger_block(_workflow())

    assert "workflow_dispatch:" not in trigger
    assert "github.event.inputs" not in trigger
    assert "types: [strix-scan]" in trigger
    assert "\n  release:" not in trigger
    assert "v*-rc*" not in trigger
    assert "scan_mode:" not in trigger


def test_required_pr_scoping_and_severity_gate_remain() -> None:
    """Mode mapping must not weaken fail-closed PR evidence."""
    step = _run_strix_step(_workflow())

    assert "STRIX_FAIL_ON_MIN_SEVERITY: MEDIUM" in step
    assert "__PR_SCOPE__" in step
    assert "STRIX_DISABLE_PR_SCOPING:" in step
    assert "github.event_name == 'pull_request_target'" in step
    assert "github.event.client_payload.pr_number" in step


@pytest.mark.parametrize("scan_mode", ("quick", "standard", "deep"))
def test_require_safe_scan_mode_accepts_official_names(scan_mode: str) -> None:
    """The gate allowlist must accept only official CLI mode names."""
    assert _require_safe_scan_mode_rc(scan_mode) == 0


@pytest.mark.parametrize(
    "scan_mode",
    ("normal", "Quick", "STANDARD", "deep ", "quick;id", "fast", ""),
)
def test_require_safe_scan_mode_rejects_unofficial_names(scan_mode: str) -> None:
    """Charset-valid aliases such as ``normal`` must still fail closed."""
    assert _require_safe_scan_mode_rc(scan_mode) == 2


def test_require_safe_scan_mode_source_has_no_normal_alias() -> None:
    """The production case list must not grow a ``normal`` arm."""
    function_source = _function_block(
        STRIX_GATE.read_text(encoding="utf-8"),
        "require_safe_scan_mode",
    )

    assert "quick | standard | deep)" in function_source
    assert "normal)" not in function_source


def test_gate_allowlist_is_reached_before_scanner_invocation() -> None:
    """An unofficial mode must fail closed before the fake scanner starts."""
    gate = STRIX_GATE.read_text(encoding="utf-8")
    allowlist_index = gate.index("require_safe_scan_mode")
    command_index = gate.index(
        'command = [resolved_strix_bin, "-n", "-t", ".", "--scan-mode", scan_mode]'
    )
    assert allowlist_index < command_index
