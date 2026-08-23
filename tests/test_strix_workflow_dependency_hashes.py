"""Supply-chain contracts for the Strix changed-path policy workflow."""

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"
PR_WORKFLOW = ROOT / ".github" / "workflows" / "strix.yml"
WORKFLOW_DISPATCH_KEY_RE = re.compile(
    r"(?m)^[ \t]+['\"]?workflow_dispatch['\"]?\s*:"
)
EXPECTED_WHEEL_HASHES = {
    "coverage==7.15.2": "b9a6367e4aff723e8ee8190836836124284e8fcd4265e307c844010cfa074f3f",
    "iniconfig==2.1.0": "9deba5723312380e77435581c6bf4935c94cbfab9b1ed33ef8d238ea168eb760",
    "packaging==26.2": "5fc45236b9446107ff2415ce77c807cee2862cb6fac22b8a73826d0693b0980e",
    "pluggy==1.6.0": "e920276dd6813095e9377c0bc5566d94c932c33b27a3e3945d8389c374dd4746",
    "pygments==2.20.0": "81a9e26dd42fd28a23a2d169d86d7ac03b46e2f8b59ed4698fb4785f946d0176",
    "pytest==9.1.1": "37a86b45efb9a47a61a36449063e8e18d0cab3161329fc099eb21783169c4f0c",
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


def test_strix_workflow_reruns_when_shared_runtime_or_doctoring_changes() -> None:
    """Shared model routing and its decision record always rerun exact-head checks."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    for path in (
        "docs/doctoring/strix-unsupported-sampling-fallback.md",
        "scripts/ci/strix_model_utils.sh",
    ):
        assert f'      - "{path}"' in workflow


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


def test_privileged_strix_workflow_never_installs_pr_head_dependencies() -> None:
    """Provider credentials must only reach code pinned by the trusted workflow."""
    workflow = PR_WORKFLOW.read_text(encoding="utf-8")

    assert "Materialize central Strix dependency lock from PR head" not in workflow
    assert 'PR_HEAD_SHA:requirements-strix-ci-hashes.txt' not in workflow
