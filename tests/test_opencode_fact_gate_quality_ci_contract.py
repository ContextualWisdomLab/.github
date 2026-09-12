"""Permanent contract wiring the OpenCode fact-gate regression test into CI.

``scripts/ci/test_opencode_fact_gate_contract.sh`` asserts that
``.github/workflows/opencode-review-dispatch.yml`` still carries the
fact-gate evidence strings that stop OpenCode review from claiming a repo
path, evidence excerpt, or reviewer thread is unavailable without proof. A
real 15-assertion contract that no workflow ever invokes enforces nothing:
this module pins that ``opencode-fact-gate-quality-ci.yml`` actually runs it
on every pull request that could change either file, and executes the
regression contract directly so a change to either file that breaks it fails
this repository's own test suite too, not only the dedicated workflow.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_CONTRACT_SCRIPT_PATH = (
    _REPOSITORY_ROOT / "scripts/ci/test_opencode_fact_gate_contract.sh"
)
_DISPATCH_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-review-dispatch.yml"
)
_QUALITY_WORKFLOW_PATH = (
    _REPOSITORY_ROOT / ".github/workflows/opencode-fact-gate-quality-ci.yml"
)


def _quality_workflow_text() -> str:
    """Return the workflow that wires the fact-gate contract into CI."""

    return _QUALITY_WORKFLOW_PATH.read_text(encoding="utf-8")


def test_quality_workflow_watches_the_contract_and_the_dispatch_workflow() -> None:
    """A change to either watched file must retrigger this quality gate."""

    quality_workflow = _quality_workflow_text()
    assert (
        '      - ".github/workflows/opencode-review-dispatch.yml"\n'
        in quality_workflow
    )
    assert (
        '      - "scripts/ci/test_opencode_fact_gate_contract.sh"\n'
        in quality_workflow
    )


def test_quality_workflow_actually_invokes_the_contract_script() -> None:
    """The workflow must execute the contract, not merely reference it."""

    quality_workflow = _quality_workflow_text()
    assert (
        "bash scripts/ci/test_opencode_fact_gate_contract.sh\n" in quality_workflow
    )
    assert 'ref: ${{ github.event.pull_request.head.sha }}' in quality_workflow


def test_quality_workflow_watched_paths_resolve_to_repository_files() -> None:
    """Every watched path in the quality workflow must exist in the repo."""

    quality_workflow = _quality_workflow_text()
    watched_section = quality_workflow.split("    paths:\n", 1)[1].split(
        "\n\npermissions:\n", 1
    )[0]
    watched_paths = [
        line.strip()[2:].strip('"')
        for line in watched_section.splitlines()
        if line.strip().startswith("- ")
    ]

    assert watched_paths
    assert str(_CONTRACT_SCRIPT_PATH.relative_to(_REPOSITORY_ROOT)) in watched_paths
    assert str(_DISPATCH_WORKFLOW_PATH.relative_to(_REPOSITORY_ROOT)) in watched_paths
    for relative_path in watched_paths:
        assert (_REPOSITORY_ROOT / relative_path).is_file(), relative_path


def test_fact_gate_contract_script_currently_passes() -> None:
    """The regression contract the workflow runs must pass right now too."""

    result = subprocess.run(
        ["bash", str(_CONTRACT_SCRIPT_PATH)],
        check=False,
        capture_output=True,
        text=True,
        cwd=_REPOSITORY_ROOT,
    )

    assert result.returncode == 0, result.stderr
    assert "OpenCode fact-gate contract OK" in result.stdout
