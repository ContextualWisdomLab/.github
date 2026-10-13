from pathlib import Path
import textwrap
from xml.etree import ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"


def workflow_text(name: str) -> str:
    """Return one central fast-mlsirm workflow as UTF-8 text."""
    return (WORKFLOWS / name).read_text(encoding="utf-8")


GPU_IDENTITIES = (
    ("tests.test_marginal_parity", "test_marginal_gpu_agrees_with_cpu_loosely"),
    ("tests.test_bifactor_gpu_high_q", "test_bifactor_gpu_parity_q121"),
    ("tests.test_bifactor_gpu_high_q", "test_bifactor_gpu_parity_q241"),
    ("tests.test_bifactor_gpu_high_q", "test_bifactor_gpu_parity_q481"),
    ("tests.test_bifactor_gpu_high_q", "test_bifactor_gpu_parity_q241_wide_items_metal_workgroups"),
    ("tests.test_bifactor_gpu_high_q", "test_bifactor_cpu_q121_vs_q241_agree"),
    ("tests.test_bifactor_bootstrap_benchmark", "test_joint_bootstrap_cpu_vs_gpu_wall_time_q121"),
)


def _gpu_suite(identities=GPU_IDENTITIES) -> ET.Element:
    suite = ET.Element("testsuite", tests=str(len(identities)), failures="0", errors="0", skipped="0")
    for classname, name in identities:
        ET.SubElement(suite, "testcase", classname=classname, name=name)
    return suite


def _run_gpu_guard(xml: ET.Element, tmp_path, monkeypatch) -> None:
    step = workflow_text("fast-mlsirm-ci.yml").split("      - name: Reject skipped GPU evidence\n", 1)[1]
    script = textwrap.dedent(step.split("python - <<'PY'\n", 1)[1].split("          PY\n", 1)[0])
    (tmp_path / "gpu-junit.xml").write_bytes(ET.tostring(xml))
    monkeypatch.chdir(tmp_path)
    exec(compile(script, "fast-mlsirm-ci.yml::gpu-junit-guard", "exec"), {})


def test_gpu_guard_accepts_only_the_exact_successful_seven(tmp_path, monkeypatch):
    """Execute the producer guard against complete and false-admission evidence."""
    _run_gpu_guard(_gpu_suite(), tmp_path, monkeypatch)
    partial = _gpu_suite(GPU_IDENTITIES[:1])
    skipped = _gpu_suite()
    ET.SubElement(skipped[0], "skipped")
    for xml in (partial, skipped):
        with pytest.raises(SystemExit):
            _run_gpu_guard(xml, tmp_path, monkeypatch)


def test_fast_mlsirm_reusable_workflows_keep_isolated_runner_and_gate_contracts():
    """Require every reusable fast-mlsirm job to use the isolated runner boundary."""
    for name in ("ci", "codeql", "statistical-studies", "hourly-pr-governance", "pypi-gap-guard"):
        text = workflow_text(f"fast-mlsirm-{name}.yml")
        assert "workflow_call:" in text
        assert "ubuntu-latest" not in text and "runs-on: ubuntu" not in text
        assert "group: CWL CI isolated" in text
        assert "labels: [self-hosted, linux, x64, cwlab-ci-isolated]" in text
        assert f"group: central-fast-mlsirm-{name}-" in text
    ci = workflow_text("fast-mlsirm-ci.yml")
    assert 'python-version: ["3.12", "3.14"]' in ci
    assert 'test "${{ needs.python-matrix.result }}" = "success"' in ci
    assert "cargo test --locked --workspace" in ci
    assert "cargo test --locked --manifest-path crates/fast-mlsirm-py/Cargo.toml" in ci


def test_disabled_release_legs_fail_the_caller_instead_of_reporting_success():
    """Expose the intentional release hold as a failing required job."""
    text = workflow_text("fast-mlsirm-publish-pypi.yml")
    assert text.count("    if: ${{ false }}") == 2
    assert "  publication-disabled:\n" in text
    assert "    needs: [sdist]\n" in text
    assert "publication disabled (release runner matrix unavailable)" in text
    assert "required macOS, Windows, and ARM self-hosted release legs" in text
    assert "          exit 1\n" in text


def test_release_dependency_gate_does_not_cross_provider_credentials():
    """Keep provider credentials behind contextual-orchestrator's boundary."""
    text = workflow_text("fast-mlsirm-publish-pypi.yml")
    gate = text.split("  dependency-gate:\n", 1)[1].split("\n  release-admission:\n", 1)[0]
    assert "secrets: inherit" not in gate
    for name in (
        "BYTEZ_API_KEY",
        "NVIDIA_NIM_API_KEY",
        "NVIDIA_NIM_API_KEY_SUB",
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
    ):
        assert name not in gate
    assert "PIPY_TOKEN" not in gate


def test_gap_guard_fails_closed_when_release_inventory_cannot_be_read():
    """Authenticate gh and propagate release-list failures before gap decisions."""
    text = workflow_text("fast-mlsirm-pypi-gap-guard.yml")
    inventory = text.split("      - name: Resolve control-plane commit and PyPI inventory\n", 1)[1]
    inventory = inventory.split("\n      - name: Dispatch publish-pypi", 1)[0]
    assert "          GH_TOKEN: ${{ github.token }}\n" in inventory
    assert '            release_tags="$(' in inventory
    assert '            done <<< "$release_tags"' in inventory
    assert "            done < <(" not in inventory
