"""Contracts for the shared exact-head coverage quality-gate reusable workflow."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


def _pyyaml_pin(requirements: str) -> tuple[str, set[str]]:
    """Read one logical requirement, ignoring lock generator comments."""
    logical = requirements.replace("\\\n", " ")
    pins = re.findall(r"(?mi)^pyyaml==([^\n]+)", logical)
    assert len(pins) == 1, "install lock must contain exactly one PyYAML pin"
    tokens = pins[0].split()
    return tokens[0], set(re.findall(r"--hash=sha256:([0-9a-f]{64})", pins[0]))


def _installed_gate_requirements(workflow: str) -> str:
    """Extract the actual parsed installation step's consumed heredoc."""
    document = yaml.load(workflow, Loader=yaml.BaseLoader)
    steps = document["jobs"]["quality-gate"]["steps"]
    installs = [
        step for step in steps
        if step.get("name") == "Install exact hash-verified quality dependencies"
    ]
    assert len(installs) == 1, "expected one dependency installation step"
    shell = installs[0]["run"]
    target = "${RUNNER_TEMP}/exact-head-coverage-quality-gate-requirements.txt"
    match = re.search(
        rf"(?m)^cat >\"{re.escape(target)}\" <<'EOF'\n(.*?)^EOF$",
        shell, re.DOTALL,
    )
    assert match is not None, "missing installation requirements heredoc"
    install = shell[match.end():].replace("\\\n", " ")
    assert "python -m pip install" in install
    assert "--require-hashes" in install
    assert f'-r "{target}"' in install, "pip must consume the extracted lock"
    return match.group(1)


def _assert_installed_pyyaml(workflow: str) -> None:
    """Bind the runtime lock to the separately admitted repository hash set."""
    declared = _pyyaml_pin(_text(ROOT / "requirements-opencode-review-ci-hashes.txt"))
    assert declared[0] == "6.0.3"
    assert len(declared[1]) == 73, "admitted PyYAML lock must retain all artifacts"
    installed = _pyyaml_pin(_installed_gate_requirements(workflow))
    assert installed == declared, "installed PyYAML version/hash set differs from admission"


def test_gate_installs_admitted_pyyaml_for_yaml_contracts() -> None:
    """The all-tests caller needs the YAML parser in its actual installed lock."""
    _assert_installed_pyyaml(_text(GATE_WORKFLOW))


@pytest.mark.parametrize("mutation", ["missing-pin", "missing-hash", "wrong-version"])
def test_gate_pyyaml_install_contract_rejects_mutations(mutation: str) -> None:
    """Each independent lock-policy weakening must be rejected by the oracle."""
    workflow = _text(GATE_WORKFLOW)
    requirements = _installed_gate_requirements(workflow)
    stanza = re.search(r"(?mi)^pyyaml==[^\n]*(?:\n[ \t]+[^\n]*)*", requirements)
    assert stanza is not None, "positive source must include the installed pin"
    if mutation == "missing-pin":
        indented = "\n".join("          " + line for line in stanza.group().splitlines())
        assert indented in workflow
        mutated = workflow.replace(indented, "", 1)
    elif mutation == "missing-hash":
        digest = re.search(r"--hash=sha256:[0-9a-f]{64}", stanza.group())
        assert digest is not None
        mutated = workflow.replace(digest.group(), "", 1)
    else:
        mutated = workflow.replace("pyyaml==6.0.3", "pyyaml==6.0.2", 1)
    assert mutated != workflow, "mutation must change actual workflow bytes"
    with pytest.raises(AssertionError, match="PyYAML"):
        _assert_installed_pyyaml(mutated)

ROOT = Path(__file__).resolve().parents[1]
GATE_WORKFLOW = ROOT / ".github/workflows/exact-head-coverage-quality-gate.yml"
JS_CALLER = ROOT / ".github/workflows/javascript-coverage-quality-ci.yml"
AGENT_QUALITY_WORKFLOW = ROOT / ".github/workflows/agent-review-runtime-quality-ci.yml"


SELF_TEST_PATH = "tests/test_exact_head_coverage_quality_gate_contract.py"


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


def test_javascript_caller_keeps_using_the_reusable_gate() -> None:
    """Retain the reusable implementation for its remaining JavaScript caller."""
    js_caller = _text(JS_CALLER)
    assert "uses: ./.github/workflows/exact-head-coverage-quality-gate.yml" in js_caller

    assert "coverage_include: scripts/ci/javascript_coverage_gate.py" in js_caller
    assert "pytest_target: tests" in js_caller
    assert "timeout_minutes: 15" in js_caller



def test_organization_loop_contract_moves_to_agent_quality_job() -> None:
    """Retire only the thin caller while preserving its exact coverage scope."""
    workflow = _text(AGENT_QUALITY_WORKFLOW)

    assert not (
        ROOT / ".github/workflows/organization-commercial-readiness-loop-quality-ci.yml"
    ).exists()
    assert "tests/test_organization_commercial_readiness_loop*.py" in workflow
    assert "--include='scripts/ci/organization_commercial_readiness_loop.py'" in workflow
    assert "--fail-under=100" in workflow


def test_js_caller_trigger_covers_this_contract_test_file() -> None:
    """An edit to only this file must still trigger the job that runs it.

    The JS caller's pytest_target is the whole `tests` directory, so it
    actually exercises this file when it runs -- unlike the org-loop caller,
    whose pytest_target is a narrower glob that never matches this filename.
    Without this file in the JS caller's path trigger, a change scoped only
    to this test could merge without the gate that runs it ever firing.
    """
    js_caller = _text(JS_CALLER)
    trigger = js_caller.split("\npermissions:\n", 1)[0]

    assert f"'{SELF_TEST_PATH}'" in trigger
