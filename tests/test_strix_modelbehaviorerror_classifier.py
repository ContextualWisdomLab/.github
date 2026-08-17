"""Regression contract for Strix ModelBehaviorError flake classification.

A trusted pydantic-ai or LiteLLM ModelBehaviorError with Vulnerabilities 0
is backend unavailability. Vulnerabilities [1-9] stay fail-closed. A
source-file mention without the SDK exception prefix is not infrastructure.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_GATE = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
STRIX_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "strix.yml"


def _function_block(source: str, function_name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) {{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _classifies_as_model_behavior_error(log_text: str) -> bool:
    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    function_source = _function_block(gate_source, "is_model_behavior_error")
    with tempfile.TemporaryDirectory(prefix="strix-mbe-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -euo pipefail",
                'STRIX_LOG="$1"',
                function_source,
                "is_model_behavior_error",
            )
        )
        completed = subprocess.run(
            ["bash", "-c", script, "strix-classifier", str(log_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode not in {0, 1}:
        raise AssertionError(completed.stderr)
    return completed.returncode == 0


def _workflow_signal_pattern(workflow: str, variable_name: str) -> str:
    match = re.search(
        rf"(?m)^\s+{re.escape(variable_name)}='([^']+)'$",
        workflow,
    )
    if match is None:
        raise AssertionError(f"missing workflow signal: {variable_name}")
    return match.group(1)


def _workflow_neutralizes(log_text: str) -> bool:
    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    backend_pattern = _workflow_signal_pattern(
        workflow,
        "backend_unavailable_signal",
    )
    vulnerability_pattern = _workflow_signal_pattern(
        workflow,
        "reported_vulnerability_signal",
    )
    with tempfile.TemporaryDirectory(prefix="strix-workflow-mbe-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        backend = subprocess.run(
            ["grep", "-Eiq", backend_pattern, str(log_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        vulnerability = subprocess.run(
            ["grep", "-Eiq", vulnerability_pattern, str(log_path)],
            check=False,
            capture_output=True,
            text=True,
        )
    if backend.returncode not in {0, 1}:
        raise AssertionError(backend.stderr)
    if vulnerability.returncode not in {0, 1}:
        raise AssertionError(vulnerability.stderr)
    return backend.returncode == 0 and vulnerability.returncode == 1


class StrixModelBehaviorErrorClassifierTests(unittest.TestCase):
    """Neutralize ModelBehaviorError flake without weakening Vulnerabilities [1-9]."""

    def test_pydantic_ai_model_behavior_error_with_zero_findings_is_infra(self) -> None:
        log = (
            "pydantic_ai.exceptions.ModelBehaviorError: "
            "unexpected tool call arguments\n"
            "Vulnerabilities 0\n"
        )
        self.assertTrue(_classifies_as_model_behavior_error(log))
        self.assertTrue(_workflow_neutralizes(log))

    def test_litellm_wrapped_model_behavior_error_with_zero_findings_is_infra(self) -> None:
        log = (
            "litellm.exceptions.APIError: ModelBehaviorError from provider\n"
            "Vulnerabilities 0\n"
        )
        self.assertTrue(_classifies_as_model_behavior_error(log))
        self.assertTrue(_workflow_neutralizes(log))

    def test_model_behavior_error_with_vulnerabilities_stays_fail_closed(self) -> None:
        log = (
            "pydantic_ai.exceptions.ModelBehaviorError: unexpected tool call\n"
            "Vulnerabilities 1\n"
        )
        self.assertTrue(_classifies_as_model_behavior_error(log))
        self.assertFalse(_workflow_neutralizes(log))

    def test_source_literal_model_behavior_error_is_not_infra(self) -> None:
        log = "raise ModelBehaviorError('spoofed from target source')\nVulnerabilities 0\n"
        self.assertFalse(_classifies_as_model_behavior_error(log))
        self.assertFalse(_workflow_neutralizes(log))

    def test_gate_wires_classifier_into_infra_and_retry(self) -> None:
        gate_source = STRIX_GATE.read_text(encoding="utf-8")
        infrastructure = _function_block(gate_source, "has_detected_infrastructure_error")
        retryable = _function_block(gate_source, "is_model_retryable_error")
        self.assertIn("is_model_behavior_error", infrastructure)
        self.assertIn("is_model_behavior_error", retryable)

    def test_reported_vulnerability_signal_still_matches_one_through_nine(self) -> None:
        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        vulnerability_pattern = _workflow_signal_pattern(
            workflow,
            "reported_vulnerability_signal",
        )
        self.assertIn("Vulnerabilities[[:space:]]+[1-9]", vulnerability_pattern)
