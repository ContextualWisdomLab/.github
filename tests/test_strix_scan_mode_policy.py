"""Event-to-mode contract for the organization-required Strix workflow.

CWL runs both GitHub Flow (main/master) and Git Flow (develop) without a
consistent RC-tag or prerelease convention. Official Strix CLI modes are only
``quick``, ``standard``, and ``deep``. This module pins the dual-flow mapping
and the Deep-only timeout raise so a revert or a 360-minute required-PR job
fails closed in CI.
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
DOCTORING = REPO_ROOT / "docs" / "doctoring" / "strix-scan-mode-dual-flow.md"
SCAN_MODE_EXPRESSION_PREFIX = "STRIX_SCAN_MODE: ${{ "
SCAN_MODE_EXPRESSION_SUFFIX = " }}"

SCAN_MODE_EXPRESSION = (
    "STRIX_SCAN_MODE: ${{ github.event_name == 'workflow_dispatch' && "
    "(github.event.inputs.scan_mode || 'standard') || "
    "github.event_name == 'schedule' && 'standard' || "
    "github.event_name == 'push' && (github.ref == 'refs/heads/main' || "
    "github.ref == 'refs/heads/master') && 'standard' || 'quick' }}"
)
JOB_TIMEOUT_EXPRESSION = (
    "timeout-minutes: ${{ fromJSON(github.event_name == 'workflow_dispatch' && "
    "github.event.inputs.scan_mode == 'deep' && '360' || '120') }}"
)
STEP_TIMEOUT_EXPRESSION = (
    "timeout-minutes: ${{ fromJSON(github.event_name == 'workflow_dispatch' && "
    "github.event.inputs.scan_mode == 'deep' && '340' || '100') }}"
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


def _pinned_scan_mode_expression() -> str:
    """Return the inner GitHub expression pinned by ``SCAN_MODE_EXPRESSION``."""
    if not SCAN_MODE_EXPRESSION.startswith(SCAN_MODE_EXPRESSION_PREFIX):
        raise AssertionError("scan-mode pin lost its GitHub expression prefix")
    if not SCAN_MODE_EXPRESSION.endswith(SCAN_MODE_EXPRESSION_SUFFIX):
        raise AssertionError("scan-mode pin lost its GitHub expression suffix")
    return SCAN_MODE_EXPRESSION[
        len(SCAN_MODE_EXPRESSION_PREFIX) : -len(SCAN_MODE_EXPRESSION_SUFFIX)
    ]


def _github_expression_tokens(expression: str) -> list[str]:
    """Tokenize a GitHub Actions ``&&`` / ``||`` / ``==`` string expression."""
    tokens: list[str] = []
    index = 0
    length = len(expression)
    while index < length:
        current = expression[index]
        if current.isspace():
            index += 1
            continue
        if expression.startswith("&&", index) or expression.startswith("||", index):
            tokens.append(expression[index : index + 2])
            index += 2
            continue
        if expression.startswith("==", index):
            tokens.append("==")
            index += 2
            continue
        if current in "()":
            tokens.append(current)
            index += 1
            continue
        if current == "'":
            end = expression.find("'", index + 1)
            if end < 0:
                raise AssertionError("unterminated GitHub expression string")
            tokens.append(expression[index : end + 1])
            index = end + 1
            continue
        if current == "." or current.isalpha() or current == "_":
            end = index + 1
            while end < length and (
                expression[end].isalnum() or expression[end] in "._"
            ):
                end += 1
            tokens.append(expression[index:end])
            index = end
            continue
        raise AssertionError(f"unsupported GitHub expression token at {index}")
    return tokens


def _github_value_is_truthy(value: str) -> bool:
    """Return whether a GitHub Actions operand continues ``&&`` / ``||``."""
    return value not in {"", "false", "0", "null"}


def _eval_github_or_and(expression: str, bindings: dict[str, str]) -> str:
    """Evaluate the pinned scan-mode expression with GitHub ``&&`` / ``||`` rules."""
    tokens = _github_expression_tokens(expression)
    index = 0

    def peek() -> str | None:
        if index >= len(tokens):
            return None
        return tokens[index]

    def consume(expected: str | None = None) -> str:
        nonlocal index
        if index >= len(tokens):
            raise AssertionError("unexpected end of GitHub expression")
        token = tokens[index]
        if expected is not None and token != expected:
            raise AssertionError(f"expected {expected!r}, found {token!r}")
        index += 1
        return token

    def parse_primary() -> str:
        token = peek()
        if token == "(":
            consume("(")
            value = parse_or()
            consume(")")
            return value
        if token is None:
            raise AssertionError("missing GitHub expression operand")
        consume()
        if token.startswith("'") and token.endswith("'"):
            return token[1:-1]
        if token not in bindings:
            raise AssertionError(f"unbound GitHub expression identifier: {token}")
        return bindings[token]

    def parse_comparison() -> str:
        left = parse_primary()
        if peek() != "==":
            return left
        consume("==")
        right = parse_primary()
        return "true" if left == right else "false"

    def parse_and() -> str:
        value = parse_comparison()
        while peek() == "&&":
            consume("&&")
            if not _github_value_is_truthy(value):
                parse_comparison()
                continue
            value = parse_comparison()
        return value

    def parse_or() -> str:
        value = parse_and()
        while peek() == "||":
            consume("||")
            if _github_value_is_truthy(value):
                parse_and()
                continue
            value = parse_and()
        return value

    result = parse_or()
    if index != len(tokens):
        raise AssertionError(f"trailing GitHub expression tokens: {tokens[index:]}")
    return result


def _eval_pinned_scan_mode(event_name: str, ref: str, scan_mode_input: str) -> str:
    """Evaluate the exact pinned workflow expression against one event."""
    return _eval_github_or_and(
        _pinned_scan_mode_expression(),
        {
            "github.event_name": event_name,
            "github.event.inputs.scan_mode": scan_mode_input,
            "github.ref": ref,
        },
    )


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


def test_pinned_scan_mode_expression_evaluator_uses_github_or_and_rules() -> None:
    """A remade Python if/elif must not be able to hide pin drift."""
    expression = _pinned_scan_mode_expression()

    assert "github.event_name == 'workflow_dispatch'" in expression
    assert "github.event_name == 'push'" in expression
    assert (
        _eval_github_or_and(
            expression,
            {
                "github.event_name": "repository_dispatch",
                "github.event.inputs.scan_mode": "",
                "github.ref": "refs/heads/main",
            },
        )
        == "quick"
    )


def test_workflow_pins_official_scan_mode_expression() -> None:
    """The job must set STRIX_SCAN_MODE from event, ref, and manual input."""
    workflow = _workflow()

    assert SCAN_MODE_EXPRESSION in workflow
    assert "client_payload.scan_mode" not in workflow
    assert "          - normal" not in workflow
    assert "|| 'normal'" not in workflow


@pytest.mark.parametrize(
    ("event_name", "ref", "scan_mode_input", "expected"),
    (
        ("pull_request_target", "refs/heads/main", "", "quick"),
        ("repository_dispatch", "refs/heads/main", "", "quick"),
        ("push", "refs/heads/develop", "", "quick"),
        ("push", "refs/heads/main", "", "standard"),
        ("push", "refs/heads/master", "", "standard"),
        ("schedule", "refs/heads/develop", "", "standard"),
        ("schedule", "refs/heads/main", "", "standard"),
        ("workflow_dispatch", "refs/heads/release-candidate", "", "standard"),
        ("workflow_dispatch", "refs/heads/main", "quick", "quick"),
        ("workflow_dispatch", "refs/heads/main", "standard", "standard"),
        ("workflow_dispatch", "refs/heads/main", "deep", "deep"),
    ),
)
def test_dual_flow_event_maps_to_official_mode(
    event_name: str,
    ref: str,
    scan_mode_input: str,
    expected: str,
) -> None:
    """Evaluate the pinned workflow expression, not a parallel Python remake."""
    assert SCAN_MODE_EXPRESSION in _workflow()
    assert _eval_pinned_scan_mode(event_name, ref, scan_mode_input) == expected
    if expected == "deep":
        assert event_name == "workflow_dispatch"
        assert scan_mode_input == "deep"


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

    assert JOB_TIMEOUT_EXPRESSION in header
    assert STEP_TIMEOUT_EXPRESSION in step
    assert "timeout-minutes: 360" not in header
    assert "timeout-minutes: 340" not in step
    assert "timeout-minutes: 360" not in step
    assert 'process_budget_seconds="5400"' in step
    assert 'total_budget_seconds="5700"' in step
    assert (
        '[ "${STRIX_SCAN_MODE}" = "deep" ] && '
        '[ "${GITHUB_EVENT_NAME}" = "workflow_dispatch" ]'
    ) in step
    assert 'process_budget_seconds="14400"' in step
    assert 'total_budget_seconds="16200"' in step


def test_doctoring_records_workflow_dispatch_revision_residual() -> None:
    """Write access remains the only control after restoring manual dispatch."""
    doctoring = DOCTORING.read_text(encoding="utf-8")

    assert "gh workflow run --ref" in doctoring
    assert "Write access is the only control" in doctoring
    assert "job-level `if:`" in doctoring
    assert "Do not add `target_repository` or `pr_number` inputs" in doctoring


def test_workflow_dispatch_is_scan_mode_only_and_keeps_dispatch_retry() -> None:
    """Manual deep/standard is not a privileged same-head retry replacement."""
    trigger = _trigger_block(_workflow())

    assert "workflow_dispatch:" in trigger
    assert "scan_mode:" in trigger
    assert "default: standard" in trigger
    assert "          - quick" in trigger
    assert "          - standard" in trigger
    assert "          - deep" in trigger
    assert "types: [strix-scan]" in trigger
    assert "\n  release:" not in trigger
    assert "v*-rc*" not in trigger
    assert "target_repository:" not in trigger.split("workflow_dispatch:", 1)[1]
    assert "pr_number:" not in trigger.split("workflow_dispatch:", 1)[1]


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
