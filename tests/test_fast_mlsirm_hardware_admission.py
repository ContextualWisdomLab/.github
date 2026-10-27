"""Exercise the real aggregate shell; fixtures never attest hardware execution."""

import os
from pathlib import Path
import re
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/fast-mlsirm-ci.yml"


def workflow():
    """Parse executable mappings, retaining GitHub's `on` key and booleans."""
    class Loader(yaml.SafeLoader):
        pass

    Loader.yaml_implicit_resolvers = {
        key: [(tag, expression) for tag, expression in resolvers
              if tag != "tag:yaml.org,2002:bool"]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    Loader.add_implicit_resolver(
        "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$", re.I), list("tTfF")
    )
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=Loader)


def run_terminal_steps(tmp_path, results):
    """Execute parsed workflow shell bodies with synthetic dependency results."""
    observations = []
    prior_failure = False
    for step in workflow()["jobs"]["python"]["steps"]:
        condition = step.get("if")
        if prior_failure and condition != "${{ always() }}":
            continue
        script = step["run"]
        for job, result in results.items():
            script = script.replace("${{ needs." + job + ".result }}", result)
        assert "${{" not in script, "unhandled expression in executable gate"
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-e", "-o", "pipefail", "-c", script],
            cwd=tmp_path,
            env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
            capture_output=True, text=True, timeout=10,
        )
        observations.append(result)
        prior_failure = prior_failure or result.returncode != 0
    assert observations, "aggregate executed no shell"
    return observations


def test_successful_software_jobs_cannot_satisfy_missing_hardware(tmp_path):
    """Predecessor falsely accepts matrix success with no admitted hardware route."""
    results = run_terminal_steps(
        tmp_path, {"python-matrix": "success", "gpu-smoke": "success"}
    )
    assert any(result.returncode != 0 for result in results), (
        "software-only aggregate accepted without hardware lease or exact-case receipts"
    )


@pytest.mark.parametrize("matrix", ["success", "failure", "cancelled", "skipped", ""])
@pytest.mark.parametrize("gpu", ["success", "failure", "cancelled", "skipped", ""])
def test_every_dependency_state_reaches_explicit_hardware_refusal(tmp_path, matrix, gpu):
    """Even successful software siblings cannot remove the explicit admission hold."""
    results = run_terminal_steps(tmp_path, {"python-matrix": matrix, "gpu-smoke": gpu})
    assert len(results) == 3
    assert results[0].returncode == (0 if matrix == "success" else 1)
    assert results[1].returncode == (0 if gpu == "success" else 1)
    assert results[2].returncode == 1
    assert "BLOCKED: mandatory hardware execution is not admitted." in results[2].stderr


def test_terminal_is_unconditional_and_retains_the_required_context():
    """Check executable fields rather than comments mentioning always()."""
    data = workflow()
    assert "workflow_call" in data["on"]
    assert yaml.safe_load("on: true") == {True: True}, "global loader was modified"
    gate = data["jobs"]["python"]
    assert gate["name"] == "python"
    assert gate["if"] == "${{ always() }}"
    assert gate["needs"] == ["python-matrix", "gpu-smoke"]
    assert gate["runs-on"] == data["jobs"]["python-matrix"]["runs-on"]
    assert all(step.get("continue-on-error", False) is False for step in gate["steps"])
    assert all(step["if"] == "${{ always() }}" for step in gate["steps"][1:])
    assert all("uses" not in step for step in gate["steps"]), "hold must not run product checkout code"


def test_existing_software_workloads_remain_selected():
    """Preserve the full matrix and all seven existing GPU obligations."""
    jobs = workflow()["jobs"]
    assert set(jobs) == {"python-matrix", "python", "rust", "gpu-smoke", "fuzz", "package"}
    assert jobs["python-matrix"]["strategy"]["matrix"]["python-version"] == ["3.12", "3.14"]
    assert jobs["python-matrix"]["steps"][-1]["run"] == "pytest"
    smoke = next(step for step in jobs["gpu-smoke"]["steps"] if step.get("name") == "Run exact GPU and study-precision evidence without a skip")
    assert smoke["env"] == {"STAGE5_HIGH_Q": "1", "STAGE5_HIGH_Q_BOOTSTRAP_REPS": "2"}
    expected = {
        "tests/test_marginal_parity.py::test_marginal_gpu_agrees_with_cpu_loosely",
        "tests/test_bifactor_gpu_high_q.py::test_bifactor_gpu_parity_q121",
        "tests/test_bifactor_gpu_high_q.py::test_bifactor_gpu_parity_q241",
        "tests/test_bifactor_gpu_high_q.py::test_bifactor_gpu_parity_q481",
        "tests/test_bifactor_gpu_high_q.py::test_bifactor_gpu_parity_q241_wide_items_metal_workgroups",
        "tests/test_bifactor_gpu_high_q.py::test_bifactor_cpu_q121_vs_q241_agree",
        "tests/test_bifactor_bootstrap_benchmark.py::test_joint_bootstrap_cpu_vs_gpu_wall_time_q121",
    }
    selected = re.findall(r"tests/\S+::\w+", smoke["run"])
    assert len(selected) == 7 and set(selected) == expected


@pytest.mark.parametrize("forged_files", [False, True], ids=["missing", "forged-success"])
def test_untrusted_receipt_or_marker_cannot_release_the_hold(tmp_path, forged_files):
    """Fake files and flags stay inert; no hardware receipt validator exists yet."""
    gate = workflow()["jobs"]["python"]["steps"][-1]
    if forged_files:
        (tmp_path / "hardware-receipt.json").write_text('{"fixture_only": true, "status": "success"}')
        (tmp_path / "hardware-junit.xml").write_text('<testsuite tests="3" failures="0" errors="0" skipped="0"/>')
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "HARDWARE_ADMITTED": "1", "STAGE5_HIGH_Q": "1"}
    result = subprocess.run(["bash", "-e", "-c", gate["run"]], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 1
    assert "BLOCKED: mandatory hardware execution is not admitted." in result.stderr
