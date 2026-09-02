"""Contracts for the shared exact-head coverage quality-gate reusable workflow."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GATE_WORKFLOW = ROOT / ".github/workflows/exact-head-coverage-quality-gate.yml"
JS_CALLER = ROOT / ".github/workflows/javascript-coverage-quality-ci.yml"
ORG_LOOP_CALLER = (
    ROOT / ".github/workflows/organization-commercial-readiness-loop-quality-ci.yml"
)


def _text(path: Path) -> str:
    assert path.is_file(), f"missing workflow file: {path}"
    return path.read_text(encoding="utf-8")


def test_gate_is_call_only_with_required_string_and_number_inputs() -> None:
    """The shared gate accepts no direct trigger and pins every input as required."""
    workflow = _text(GATE_WORKFLOW)
    header = workflow.split("\npermissions:\n", 1)[0]

    assert re.search(r"(?m)^  workflow_call:\s*$", header)
    for forbidden_trigger in ("pull_request", "push", "schedule", "workflow_dispatch"):
        assert not re.search(rf"(?m)^  {forbidden_trigger}:\s*$", header)

    required_inputs = {
        "timeout_minutes": "number",
        "pytest_target": "string",
        "coverage_include": "string",
        "compileall_targets": "string",
    }
    for input_name, input_type in required_inputs.items():
        input_match = re.search(
            rf"(?ms)^      {re.escape(input_name)}:\n(?P<body>(?:^        .*\n)+)",
            header,
        )
        assert input_match is not None, f"missing workflow input: {input_name}"
        body = input_match.group("body")
        assert re.search(r"(?m)^        required: true\s*$", body)
        assert re.search(rf"(?m)^        type: {input_type}\s*$", body)


def test_gate_enforces_exact_head_and_full_branch_coverage() -> None:
    """The gate itself carries the exact-head check and the coverage fail-under."""
    workflow = _text(GATE_WORKFLOW)

    assert 'test "$(git rev-parse HEAD)" = "${{ github.event.pull_request.head.sha || github.sha }}"' in workflow
    assert "coverage run --branch -m pytest --import-mode=importlib" in workflow
    assert "--fail-under=100" in workflow
    assert "git diff --exit-code" in workflow
    assert "persist-credentials: false" in workflow


def _run_blocks(workflow: str) -> list[str]:
    """Return every indentation-bounded multiline shell body in a workflow."""
    lines = workflow.splitlines()
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "run: |":
            index += 1
            continue
        run_indent = len(lines[index]) - len(lines[index].lstrip())
        index += 1
        body: list[str] = []
        while index < len(lines) and (
            lines[index].strip() == ""
            or len(lines[index]) - len(lines[index].lstrip()) > run_indent
        ):
            body.append(lines[index])
            index += 1
        blocks.append("\n".join(body))
    return blocks


def test_gate_never_interpolates_caller_inputs_directly_into_shell() -> None:
    """Caller-controlled inputs must enter shell commands only through env vars."""
    workflow = _text(GATE_WORKFLOW)

    run_blocks = _run_blocks(workflow)
    assert run_blocks, "gate workflow must declare multiline run blocks"
    for block in run_blocks:
        assert "${{ inputs." not in block, (
            "workflow_call input must enter shell commands through an "
            f"environment variable, not direct interpolation: {block}"
        )

    for env_var in ("PYTEST_TARGET", "COVERAGE_INCLUDE", "COMPILEALL_TARGETS"):
        assert f"{env_var}: ${{{{ inputs." in workflow, (
            f"expected {env_var} to be bound from a workflow_call input via env:"
        )


def test_javascript_and_organization_loop_callers_wire_distinct_subsystem_inputs() -> None:
    """Each caller delegates to the shared gate with its own subsystem scope."""
    js_caller = _text(JS_CALLER)
    org_caller = _text(ORG_LOOP_CALLER)

    for caller in (js_caller, org_caller):
        assert (
            "uses: ./.github/workflows/exact-head-coverage-quality-gate.yml" in caller
        )

    assert "coverage_include: scripts/ci/javascript_coverage_gate.py" in js_caller
    assert "pytest_target: tests" in js_caller
    assert "timeout_minutes: 15" in js_caller

    assert (
        "coverage_include: scripts/ci/organization_commercial_readiness_loop.py"
        in org_caller
    )
    assert (
        'pytest_target: "tests/test_organization_commercial_readiness_loop*.py"'
        in org_caller
    )
    assert "timeout_minutes: 10" in org_caller
