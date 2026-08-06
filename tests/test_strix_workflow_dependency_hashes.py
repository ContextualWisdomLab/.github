"""Supply-chain contracts for the Strix changed-path policy workflow."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"
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
    for requirement, digest in EXPECTED_WHEEL_HASHES.items():
        assert f"{requirement} --hash=sha256:{digest}" in workflow


def test_strix_workflow_reruns_when_hash_contract_changes() -> None:
    """Changing this regression contract must trigger the exact-head workflow."""
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert '      - "tests/test_strix_workflow_dependency_hashes.py"' in workflow
