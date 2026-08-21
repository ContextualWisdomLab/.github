"""Regression contract for Strix ModelBehaviorError protocol flakes.

A ModelBehaviorError with zero reported vulnerabilities is retryable model
evidence. Real vulnerability counts remain fail-closed.
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
QUALITY_WORKFLOW = (
    REPOSITORY_ROOT / ".github" / "workflows" / "strix-changed-path-quality-ci.yml"
)


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace."""

    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) {{\n.*?^}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _classifies_as_model_behavior_error(log_text: str) -> bool:
    """Execute the production classifier against a bounded synthetic log."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    function_source = _function_block(gate_source, "is_model_behavior_error")
    with tempfile.TemporaryDirectory(prefix="strix-model-behavior-") as temp_dir:
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
    """Extract one single-quoted POSIX ERE assigned in the Strix workflow."""

    match = re.search(
        rf"(?m)^\s+{re.escape(variable_name)}='([^']+)'$",
        workflow,
    )
    if match is None:
        raise AssertionError(f"missing workflow signal: {variable_name}")
    return match.group(1)


def _workflow_neutralizes(log_text: str) -> bool:
    """Execute the outer workflow's backend-neutralization condition."""

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


class StrixModelBehaviorErrorTests(unittest.TestCase):
    """Protect protocol flakes without weakening vulnerability fail-closed."""

    def test_runtime_model_behavior_error_is_retryable(self) -> None:
        """Recognize the exact PascalCase Strix agent-protocol exception."""

        log = (
            "strix.agents.base.ModelBehaviorError: tool protocol mismatch\n"
            "Vulnerabilities 0\n"
        )
        self.assertTrue(_classifies_as_model_behavior_error(log))

    def test_lowercase_application_prose_is_not_retryable(self) -> None:
        """Reject target-application text that only resembles the exception."""

        log = "the model behavior error was logged by the scanned service\n"
        self.assertFalse(_classifies_as_model_behavior_error(log))
        self.assertFalse(_classifies_as_model_behavior_error("ModelBehaviorError\n"))

    def test_agents_sdk_tool_protocol_failure_is_retryable(self) -> None:
        """Recognize the OpenAI Agents SDK exception observed in required CI."""

        log = (
            "agents.exceptions.ModelBehaviorError: Tool ls not found in agent strix\n"
            "Vulnerabilities 0\n"
        )
        self.assertTrue(_classifies_as_model_behavior_error(log))

    def test_behavior_error_skips_same_model_and_enters_fallback(self) -> None:
        """Wire the classifier into infrastructure and cross-model fallback."""

        gate_source = STRIX_GATE.read_text(encoding="utf-8")
        infrastructure = _function_block(
            gate_source,
            "has_detected_infrastructure_error",
        )
        retryable = _function_block(gate_source, "is_model_retryable_error")
        same_model_retry = _function_block(
            gate_source,
            "is_transient_same_model_retry_error",
        )

        self.assertIn("is_model_behavior_error", infrastructure)
        self.assertIn("is_model_behavior_error", retryable)
        self.assertNotIn("is_model_behavior_error", same_model_retry)

    def test_outer_workflow_neutralizes_zero_finding_protocol_flake(self) -> None:
        """Empty scans that only hit ModelBehaviorError may skip."""

        self.assertTrue(
            _workflow_neutralizes(
                "strix.agents.base.ModelBehaviorError: tool protocol mismatch\n"
                "Vulnerabilities 0\n"
            )
        )
        self.assertFalse(
            _workflow_neutralizes("ModelBehaviorError\nVulnerabilities 0\n")
        )

    def test_outer_workflow_never_neutralizes_reported_vulnerabilities(self) -> None:
        """Keep a real vulnerability signal blocking despite protocol failure."""

        self.assertFalse(
            _workflow_neutralizes(
                "strix.agents.base.ModelBehaviorError: tool protocol mismatch\n"
                "Vulnerabilities 1\n"
            )
        )
        self.assertFalse(
            _workflow_neutralizes(
                "strix.agents.base.ModelBehaviorError: tool protocol mismatch\n"
                "Vulnerabilities 9\n"
            )
        )

    def test_workflow_keeps_fail_closed_vulnerability_contract(self) -> None:
        """Retain the static fail-closed vulnerability evidence contract."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ModelBehaviorError", workflow)
        self.assertIn("reported_vulnerability_signal", workflow)
        self.assertIn("Vulnerabilities[[:space:]]+[1-9]", workflow)
        self.assertIn(
            '! grep -Eiq "$reported_vulnerability_signal"',
            workflow,
        )

    def test_quality_trigger_includes_model_behavior_contracts(self) -> None:
        """Keep classifier, doctoring, and workflow edits on the quality path."""

        workflow = QUALITY_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('      - "docs/doctoring/strix-model-behavior-error.md"', workflow)
        self.assertIn('      - "tests/test_strix_model_behavior_error.py"', workflow)


if __name__ == "__main__":
    unittest.main()
