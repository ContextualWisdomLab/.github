"""Execute both failed-check emitters without GitHub or model access."""

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SANDBOX_SIGNAL = (
    "STRIX_PROVIDER_UNAVAILABLE: STRIX_SANDBOX_UNAVAILABLE: bootstrap failed"
)


@pytest.mark.parametrize("changed_path", [
    "scripts/ci/emit_opencode_failed_check_fallback_findings.sh",
    "tests/test_strix_fallback_attribution.py",
])
def test_either_owned_path_selects_the_existing_opencode_contract_job(changed_path):
    """Helper-only and test-only edits must execute this check without another job."""
    workflow_text = (REPO_ROOT / ".github/workflows/agent-review-runtime-quality-ci.yml").read_text(
        encoding="utf-8"
    )
    trigger_text = workflow_text.split("on:\n", 1)[1].split("\nconcurrency:\n", 1)[0]
    assert f'      - "{changed_path}"' in trigger_text
    selector_text = workflow_text.split('            case "$changed_path" in\n', 1)[1].split(
        "            esac", 1
    )[0]
    result = subprocess.run([
        "bash", "-c",
        'set -euo pipefail\nopencode_suite=false\nchanged_path="$1"\ncase "$changed_path" in\n'
        + selector_text + 'esac\nprintf "%s" "$opencode_suite"',
        "selector-test", changed_path,
    ], capture_output=True, text=True, check=True, env={"PATH": os.defpath})
    assert result.stdout == "true"
    step_text = workflow_text.split("- name: Verify OpenCode Rust coverage toolchain contract", 1)[1].split(
        "\n      - name:", 1
    )[0]
    assert "tests/test_strix_fallback_attribution.py" in step_text


def run_emitter(tmp_path: Path, route_name: str, evidence_text: str) -> subprocess.CompletedProcess:
    """Run the real helper or its actual missing-helper workflow fallback."""
    evidence_file = tmp_path / "failed-checks.md"
    evidence_file.write_text(evidence_text, encoding="utf-8")
    fixture_repo = tmp_path / "repository"
    fixture_repo.mkdir()
    (fixture_repo / "README.md").write_text("Fixture source line.\n", encoding="utf-8")
    helper_file = REPO_ROOT / "scripts/ci/emit_opencode_failed_check_fallback_findings.sh"
    command_args = ["bash", str(helper_file), str(evidence_file), str(fixture_repo)]
    if route_name == "inline":
        workflow_text = (REPO_ROOT / ".github/workflows/opencode-review-dispatch.yml").read_text(
            encoding="utf-8"
        )
        start_index = workflow_text.index("          emit_line_specific_fallback_findings() {")
        end_index = workflow_text.index("\n          }", start_index) + len("\n          }")
        function_text = textwrap.dedent(workflow_text[start_index:end_index])
        command_args = [
            "bash", "-c",
            'set -euo pipefail\n' + function_text + '\nemit_line_specific_fallback_findings "$1"',
            "fallback-test", str(evidence_file),
        ]
    return subprocess.run(
        command_args, cwd=fixture_repo, capture_output=True, text=True, check=False,
        env={"PATH": os.defpath, "GITHUB_WORKSPACE": str(fixture_repo)},
    )


@pytest.mark.parametrize("route_name", ["helper", "inline"])
def test_sandbox_bootstrap_does_not_invent_a_provider_or_source_finding(tmp_path, route_name):
    """A sandbox-only failed scan remains incomplete without a fabricated finding."""
    result = run_emitter(tmp_path, route_name, f"## Failed check: Strix Security Scan/strix\n{SANDBOX_SIGNAL}\n")
    assert result.returncode == 1
    assert "Strix sandbox bootstrap failure" in result.stderr
    assert "Do not approve" in result.stderr
    assert "No PR review was posted" in result.stderr
    assert "### 1." not in result.stdout
    assert "gateway or its discovered provider pool was unavailable" not in result.stdout


@pytest.mark.parametrize("route_name", ["helper", "inline"])
@pytest.mark.parametrize("evidence_text", [
    "## Failed check: Strix Security Scan/strix\nSTRIX_SANDBOX_UNAVAILABLE: bootstrap failed\n",
    f"## Failed check: Strix Security Scan/strix\nUnknown failure\n## Failed check: Unit tests\n{SANDBOX_SIGNAL}\n",
])
def test_sandbox_signal_requires_the_paired_marker_in_the_strix_check(tmp_path, route_name, evidence_text):
    """Unrelated checks and a bare substring are not authoritative sandbox evidence."""
    result = run_emitter(tmp_path, route_name, evidence_text)
    assert result.returncode == 1
    assert "Strix sandbox bootstrap failure" not in result.stderr
    assert "### 1." not in result.stdout


@pytest.mark.parametrize("route_name", ["helper", "inline"])
@pytest.mark.parametrize("sandbox_line", ["", SANDBOX_SIGNAL + "\n", SANDBOX_SIGNAL + "; "])
def test_provider_evidence_keeps_its_existing_classification(tmp_path, route_name, sandbox_line):
    """Adding a sandbox distinction must not remove independent provider evidence."""
    result = run_emitter(tmp_path, route_name, f"## Failed check: Strix Security Scan/strix\n{sandbox_line}RateLimitError\n")
    assert result.returncode == 0
    assert "### 1. HIGH" in result.stdout
    assert "provider" in result.stdout
    assert ("Strix sandbox bootstrap failure" in result.stderr) == bool(sandbox_line)


@pytest.mark.parametrize("source_path", ["README.md", "missing_source.py"])
def test_sandbox_signal_preserves_a_separately_reported_vulnerability(tmp_path, source_path):
    """Emitted findings are not a passing scan, even when the helper exits zero."""
    evidence_text = f"""## Failed check: Strix Security Scan/strix
{SANDBOX_SIGNAL}

### Strix vulnerability report window 1
Model openai/example-model Vulnerabilities 1
│ Vulnerability Report
│ Title: Fixture vulnerability
│ Severity: HIGH
│ Endpoint: /example
│ Code Locations
│ Location 1: {source_path}:1
"""
    result = run_emitter(tmp_path, "helper", evidence_text)
    if source_path == "README.md":
        assert result.returncode == 0
        assert "HIGH README.md:1 - Strix report from openai/example-model: Fixture vulnerability" in result.stdout
    else:
        assert result.returncode == 1
        assert "Unmapped Strix report" in result.stderr
        assert "openai/example-model" in result.stderr
        assert "Fixture vulnerability" in result.stderr
        assert "HIGH" in result.stderr
        assert "did not include a mappable Code Location" in result.stderr
        assert "### 1." not in result.stdout
    assert "### 2." not in result.stdout
    assert "Strix sandbox bootstrap failure" in result.stderr
    assert "no Strix Vulnerability Report window was produced" not in result.stdout
