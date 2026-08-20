"""Supply-chain contracts for the Strix changed-path policy workflow."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"
WORKFLOW_DISPATCH_KEY_RE = re.compile(
    r"(?m)^[ \t]+['\"]?workflow_dispatch['\"]?\s*:"
)
EXPECTED_WHEEL_HASHES = {
    "attrs==26.1.0": "c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309",
    "click==8.4.2": "9a6cea6e60b17ebe0a44c5cc636d94f09bd66142c1cd7d8b4cd731c4917a15f6",
    "colorama==0.4.6": "08695f5cb7ed6e0531a20572697297273c47b8cae5a63ffc6d6ed5c201be6e44",
    "coverage==7.15.2": "b9a6367e4aff723e8ee8190836836124284e8fcd4265e307c844010cfa074f3f",
    "iniconfig==2.1.0": "9deba5723312380e77435581c6bf4935c94cbfab9b1ed33ef8d238ea168eb760",
    "interrogate==1.7.0": "a320d6ec644dfd887cc58247a345054fc4d9f981100c45184470068f4b3719b0",
    "packaging==26.2": "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e",
    "pluggy==1.6.0": "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746",
    "py==1.11.0": "51c75c4126074b472f746a24399ad32f6053d1b34b68d2fa41e558e6f4a98719",
    "pygments==2.20.0": "81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176",
    "pytest==9.1.1": "37a86b45efb9a47a61a36449063e8e18d0cab3161329fc099eb21783169c4f0c",
    "pytest-asyncio==1.4.0": "933ca923a23075a87fb7070c0ec272a6848489824d887c85c812670932835aa1",
    "pytest-cov==7.1.0": "30674f2b5f6351aa09702a9c8c364f6a01c27aae0c1366ae8016160d1efc56b2",
    "tabulate==0.10.0": "e2cfde8f79420f6deeffdeda9aaec3b6bc5abce947655d17ac662b126e48a60d",
    "typing-extensions==4.16.0": "481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8",
}


def test_strix_workflow_installs_only_hash_verified_wheels() -> None:
    """Every network-installed test dependency is versioned and hash verified."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "--only-binary=:all:" in workflow
    assert "--require-hashes" in workflow
    assert 'cat >"${RUNNER_TEMP}/strix-quality-requirements.txt"' in workflow
    assert '-r "${RUNNER_TEMP}/strix-quality-requirements.txt"' in workflow
    for requirement, digest in EXPECTED_WHEEL_HASHES.items():
        assert f"{requirement} --hash=sha256:{digest}" in workflow


def test_strix_workflow_reruns_when_hash_contract_changes() -> None:
    """Changing this regression contract must trigger the exact-head workflow."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '      - "tests/test_strix_workflow_dependency_hashes.py"' in workflow


def test_strix_workflow_rejects_branch_selected_manual_dispatch() -> None:
    """Central executable workflows load no branch-selected manual source."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert WORKFLOW_DISPATCH_KEY_RE.search(workflow) is None


@pytest.mark.parametrize(
    "yaml_key",
    (
        "workflow_dispatch:",
        "workflow_dispatch :",
        "'workflow_dispatch':",
        '"workflow_dispatch":',
    ),
)
def test_manual_dispatch_guard_recognizes_valid_yaml_key_spellings(
    yaml_key: str,
) -> None:
    """The manual-dispatch guard must recognize equivalent YAML key spellings."""
    synthetic_workflow = f"on:\n  {yaml_key}\n"

    assert WORKFLOW_DISPATCH_KEY_RE.search(synthetic_workflow) is not None


def test_strix_workflow_runs_complete_shell_regression_suite() -> None:
    """Run and retrigger on the shell regressions that pytest cannot collect."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '      - "scripts/ci/test_strix_quick_gate.sh"' in workflow
    assert "bash scripts/ci/test_strix_quick_gate.sh" in workflow
    assert "bash -n scripts/ci/strix_quick_gate.sh" in workflow
