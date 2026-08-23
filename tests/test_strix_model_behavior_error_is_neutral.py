"""Regression contract for Strix ModelBehaviorError infrastructure flakes.

Strix runs through the OpenAI Agents SDK. When a model emits a malformed
tool call the SDK raises ``agents.exceptions.ModelBehaviorError`` and the
scan aborts. LiteLLM wraps the same abort as
``litellm.exceptions.APIError: ... ModelBehaviorError``. Job 95148793283
on LineageWeave PR #74 printed ``Vulnerabilities 0`` then failed the
required check because the outer workflow did not classify that abort as
backend-unavailable.

This contract keeps that flake as a neutral skip when -- and only when --
a trusted LiteLLM or agents SDK marker shares a physical log line with
``ModelBehaviorError`` and no ``Vulnerabilities [1-9]`` signal is present.
Target-source text, cross-line assembly, and real findings stay fail-closed.
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

AGENTS_SDK_MODEL_BEHAVIOR_ERROR = (
    "Model nvidia_nim/nvidia/nemotron-3-super-120b-a12b\n"
    "Vulnerabilities 0\n"
    "agents.exceptions.ModelBehaviorError: Tool create_vulnerability_report "
    "not found in agent strix\n"
    "Strix run failed for model 'nvidia_nim/nvidia/nemotron-3-super-120b-a12b' "
    "after 41s (exit code 1).\n"
    "Strix scan failed after provider infrastructure or failure-signal "
    "output; failing closed.\n"
)

LITELLM_WRAPPED_MODEL_BEHAVIOR_ERROR = (
    "litellm.exceptions.APIError: ModelBehaviorError - invalid tool call\n"
    "Vulnerabilities 0\n"
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
    backend_pattern = _workflow_signal_pattern(workflow, "backend_unavailable_signal")
    vulnerability_pattern = _workflow_signal_pattern(
        workflow, "reported_vulnerability_signal"
    )
    with tempfile.TemporaryDirectory(prefix="strix-model-behavior-wf-") as temp_dir:
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


class StrixModelBehaviorErrorIsNeutralTests(unittest.TestCase):
    """Protect the PR #74-shaped ModelBehaviorError flake without weakening the gate."""

    def test_agents_sdk_model_behavior_error_is_classified(self) -> None:
        self.assertTrue(_classifies_as_model_behavior_error(AGENTS_SDK_MODEL_BEHAVIOR_ERROR))

    def test_litellm_wrapped_model_behavior_error_is_classified(self) -> None:
        self.assertTrue(
            _classifies_as_model_behavior_error(LITELLM_WRAPPED_MODEL_BEHAVIOR_ERROR)
        )

    def test_source_literal_without_trusted_sdk_context_is_not_classified(self) -> None:
        log = "source literal: ModelBehaviorError\nVulnerabilities 0\n"
        self.assertFalse(_classifies_as_model_behavior_error(log))

    def test_provider_and_exception_must_share_one_log_line(self) -> None:
        log = (
            "litellm.exceptions.APIError: provider unavailable\n"
            "ModelBehaviorError\n"
            "Vulnerabilities 0\n"
        )
        self.assertFalse(_classifies_as_model_behavior_error(log))

    def test_classifier_is_wired_into_infrastructure_retry_and_same_model_retry(self) -> None:
        gate_source = STRIX_GATE.read_text(encoding="utf-8")
        infrastructure = _function_block(gate_source, "has_detected_infrastructure_error")
        retryable = _function_block(gate_source, "is_model_retryable_error")
        same_model_retry = _function_block(
            gate_source, "is_transient_same_model_retry_error"
        )

        self.assertIn("is_model_behavior_error", infrastructure)
        self.assertIn("is_model_behavior_error", retryable)
        self.assertIn("is_model_behavior_error", same_model_retry)

    def test_workflow_neutralizes_agents_sdk_abort_with_zero_findings(self) -> None:
        self.assertTrue(_workflow_neutralizes(AGENTS_SDK_MODEL_BEHAVIOR_ERROR))

    def test_workflow_neutralizes_litellm_wrapped_abort_with_zero_findings(self) -> None:
        self.assertTrue(_workflow_neutralizes(LITELLM_WRAPPED_MODEL_BEHAVIOR_ERROR))

    def test_workflow_rejects_source_literal_without_trusted_context(self) -> None:
        self.assertFalse(
            _workflow_neutralizes("source literal: ModelBehaviorError\nVulnerabilities 0\n")
        )

    def test_workflow_rejects_cross_line_signal_assembly(self) -> None:
        self.assertFalse(
            _workflow_neutralizes(
                "litellm.exceptions.APIError: provider unavailable\n"
                "ModelBehaviorError\n"
                "Vulnerabilities 0\n"
            )
        )

    def test_still_fails_closed_when_a_real_vulnerability_is_also_reported(self) -> None:
        log = AGENTS_SDK_MODEL_BEHAVIOR_ERROR + (
            "Vulnerability Report\nSeverity: CRITICAL\nVulnerabilities 1\n"
        )
        self.assertFalse(_workflow_neutralizes(log))
        self.assertFalse(
            _workflow_neutralizes(
                "litellm.exceptions.APIError: ModelBehaviorError - invalid tool call\n"
                "Vulnerabilities 1\n"
            )
        )

    def test_workflow_keeps_fail_closed_vulnerability_evidence_contract(self) -> None:
        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("ModelBehaviorError", workflow)
        self.assertIn(r"agents\.exceptions\.ModelBehaviorError", workflow)
        self.assertIn("reported_vulnerability_signal", workflow)
        self.assertIn("Vulnerabilities[[:space:]]+[1-9]", workflow)
        self.assertIn(
            '! grep -Eiq "$reported_vulnerability_signal"',
            workflow,
        )


if __name__ == "__main__":
    unittest.main()
