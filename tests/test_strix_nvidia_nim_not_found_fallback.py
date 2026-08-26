"""Regression contract for NVIDIA NIM model retirement and hosted 404 fallback.

The central Strix workflow must not turn a provider-side model-catalog 404 into a
security finding or retry the same unavailable model. It must move to another
approved free NVIDIA NIM candidate before using the existing GitHub Models
fallbacks, while ordinary application 404 output remains non-retryable.
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
DEFAULT_NVIDIA_MODEL = "nvidia_nim/nvidia/nemotron-3-super-120b-a12b"
FREE_NVIDIA_FALLBACK = (
    "nvidia_nim/nvidia/nemotron-4-340b-instruct"
)
RETIRED_PRIMARY_MODEL = "nvidia_nim/nvidia/nemotron-3-ultra-550b-a55b"


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace.

    The relevant Strix classifier functions contain no nested top-level function
    declarations. Requiring a brace on a line by itself keeps extraction bounded
    and makes source-shape drift fail the test instead of silently selecting the
    wrong shell code.
    """

    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _classifies_as_nvidia_not_found(log_text: str) -> bool:
    """Execute the production classifier against a bounded synthetic log."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    function_source = _function_block(
        gate_source,
        "is_nvidia_nim_not_found_error",
    )
    with tempfile.TemporaryDirectory(prefix="strix-nvidia-404-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -euo pipefail",
                'STRIX_LOG="$1"',
                function_source,
                "is_nvidia_nim_not_found_error",
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


def _workflow_classifies_backend_unavailable(log_text: str) -> bool:
    """Execute the outer workflow's backend-neutralization condition."""

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    backend_pattern = _workflow_signal_pattern(
        workflow,
        "backend_unavailable_signal",
    )
    model_behavior_pattern = _workflow_signal_pattern(
        workflow,
        "model_behavior_error_signal",
    )
    vulnerability_pattern = _workflow_signal_pattern(
        workflow,
        "reported_vulnerability_signal",
    )
    with tempfile.TemporaryDirectory(prefix="strix-workflow-404-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        backend = subprocess.run(
            ["grep", "-Eiq", backend_pattern, str(log_path)],
            check=False,
            capture_output=True,
            text=True,
        )
        model_behavior = subprocess.run(
            ["grep", "-Eq", model_behavior_pattern, str(log_path)],
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
    if model_behavior.returncode not in {0, 1}:
        raise AssertionError(model_behavior.stderr)
    if vulnerability.returncode not in {0, 1}:
        raise AssertionError(vulnerability.stderr)
    return (
        (backend.returncode == 0 or model_behavior.returncode == 0)
        and vulnerability.returncode == 1
    )


class StrixNvidiaNotFoundFallbackTests(unittest.TestCase):
    """Protect provider-scoped 404 fallback without weakening security gates."""

    def test_nvidia_hosted_model_404_is_retryable_provider_evidence(self) -> None:
        """Recognize the exact LiteLLM/NVIDIA 404 observed in required CI."""

        log = (
            "litellm.exceptions.NotFoundError: Nvidia_nimException - "
            "Error code: 404\n"
            "Vulnerabilities 0\n"
        )
        self.assertTrue(_classifies_as_nvidia_not_found(log))

    def test_application_404_without_nvidia_context_is_not_retryable(self) -> None:
        """Do not let target-application HTTP 404 text bypass security evidence."""

        log = "GET /api/project_record/unknown 404\nNotFoundError: record missing\n"
        self.assertFalse(_classifies_as_nvidia_not_found(log))

    def test_provider_and_404_signals_must_share_one_log_line(self) -> None:
        """Reject cross-line signal assembly from untrusted scan-target output."""

        log = (
            "source literal: Nvidia_nimException\n"
            "GET /api/project_record/unknown Error code: 404\n"
        )
        self.assertFalse(_classifies_as_nvidia_not_found(log))

    def test_provider_literal_without_litellm_error_is_not_retryable(self) -> None:
        """Reject source text that imitates an NVIDIA provider error line."""

        log = "source literal: Nvidia_nimException Error code: 404\n"
        self.assertFalse(_classifies_as_nvidia_not_found(log))

    def test_not_found_skips_same_model_and_enters_cross_model_fallback(self) -> None:
        """Wire the classifier only into infrastructure and model fallback."""

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

        self.assertIn("is_nvidia_nim_not_found_error", infrastructure)
        self.assertIn("is_nvidia_nim_not_found_error", retryable)
        self.assertNotIn("is_nvidia_nim_not_found_error", same_model_retry)

    def test_workflow_uses_available_free_first_nvidia_plan(self) -> None:
        """Prefer a documented hosted NIM and another NIM before GitHub."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        default_expression = (
            "steps.target_visibility.outputs.is_private == 'false' && "
            f"'{DEFAULT_NVIDIA_MODEL}' || 'gpt-5.4'"
        )
        self.assertIn(default_expression, workflow)
        self.assertIn(
            f'[ "$strix_model" = "{DEFAULT_NVIDIA_MODEL}" ] '
            '&& [ -z "${STRIX_NVIDIA_NIM_API_KEY:-}" ]',
            workflow,
        )
        self.assertIn(
            "steps.gate.outputs.provider_mode == 'nvidia_nim' && "
            f"'{FREE_NVIDIA_FALLBACK} openai-direct/gpt-5.4'",
            workflow,
        )

        default_gate = workflow.split("- name: Gate Strix secrets", maxsplit=1)[1]
        default_gate = default_gate.split(
            "- name: Prepare LLM API key input file",
            maxsplit=1,
        )[0]
        self.assertNotIn(RETIRED_PRIMARY_MODEL, default_gate)

    def test_outer_workflow_requires_litellm_context_for_nvidia_404(self) -> None:
        """Reject provider-like target text in the outer neutralization gate."""

        self.assertFalse(
            _workflow_classifies_backend_unavailable(
                "source literal: Nvidia_nimException Error code: 404\n"
            )
        )
        self.assertTrue(
            _workflow_classifies_backend_unavailable(
                "litellm.exceptions.NotFoundError: Nvidia_nimException - "
                "Error code: 404\nVulnerabilities 0\n"
            )
        )

    def test_outer_workflow_rejects_cross_line_signal_assembly(self) -> None:
        """Require exception, provider, and 404 evidence on one physical line."""

        self.assertFalse(
            _workflow_classifies_backend_unavailable(
                "litellm.exceptions.NotFoundError: provider unavailable\n"
                "Nvidia_nimException Error code: 404\n"
            )
        )

    def test_outer_workflow_rejects_nvidia_404_without_litellm_context(self) -> None:
        """Require LiteLLM NotFoundError context, not just NVIDIA + 404."""

        self.assertFalse(
            _workflow_classifies_backend_unavailable(
                "Nvidia_nimException Error code: 404\nVulnerabilities 0\n"
            )
        )

    def test_outer_workflow_never_classifies_reported_vulnerabilities(self) -> None:
        """Keep a real vulnerability signal blocking despite provider failure."""

        self.assertFalse(
            _workflow_classifies_backend_unavailable(
                "litellm.exceptions.NotFoundError: Nvidia_nimException - "
                "Error code: 404\nVulnerabilities 1\n"
            )
        )

    def test_workflow_classifies_backend_unavailable_only_nvidia_404_without_findings(self) -> None:
        """Retain the static fail-closed vulnerability evidence contract."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("Nvidia_nimException", workflow)
        self.assertIn("Error code:[[:space:]]*404", workflow)
        self.assertIn("reported_vulnerability_signal", workflow)
        self.assertIn("Vulnerabilities[[:space:]]+[1-9]", workflow)
        self.assertIn("model_behavior_error_signal=", workflow)
        self.assertIn("agents|pydantic_ai|strix", workflow)
        self.assertIn(
            '! grep -Eiq "$reported_vulnerability_signal"',
            workflow,
        )
        self.assertIn("::error title=STRIX_PROVIDER_UNAVAILABLE::", workflow)
        self.assertIn('exit "$strix_rc"', workflow)
        self.assertNotIn("Treating as a neutral skip", workflow)

    def test_outer_workflow_classifies_backend_unavailable_model_behavior_error_without_findings(
        self,
    ) -> None:
        """Require the actual scanner ModelBehaviorError format before classifying."""

        self.assertFalse(
            _workflow_classifies_backend_unavailable("ModelBehaviorError\nVulnerabilities 0\n")
        )
        self.assertTrue(
            _workflow_classifies_backend_unavailable(
                "agents.exceptions.ModelBehaviorError: provider response failed\n"
                "Vulnerabilities 0\n"
            )
        )

    def test_outer_workflow_never_classifies_model_behavior_error_with_findings(
        self,
    ) -> None:
        """Keep Vulnerabilities [1-9] fail-closed for the actual model exception."""

        self.assertFalse(
            _workflow_classifies_backend_unavailable(
                "agents.exceptions.ModelBehaviorError: provider response failed\n"
                "Vulnerabilities 1\n"
            )
        )

    def test_outer_workflow_classifies_caido_bootstrap_failure_without_findings(self) -> None:
        """Treat a Strix-owned Caido bootstrap outage as incomplete infrastructure evidence."""

        self.assertTrue(
            _workflow_classifies_backend_unavailable(
                "Error during penetration test: loginAsGuest failed after 10 attempts: "
                "curl exit 7: curl: (7) Failed to connect to 127.0.0.1 port 48080\n"
                "Vulnerabilities 0\n"
            )
        )

    def test_outer_workflow_never_downgrades_caido_failure_with_findings(self) -> None:
        """Keep a real finding blocking even when the Strix container also failed."""

        self.assertFalse(
            _workflow_classifies_backend_unavailable(
                "Error during penetration test: loginAsGuest failed after 10 attempts: "
                "curl exit 7: curl: (7) Failed to connect to 127.0.0.1 port 48080\n"
                "Vulnerabilities 1\n"
            )
        )
        self.assertFalse(
            _workflow_classifies_backend_unavailable(
                "agents.exceptions.ModelBehaviorError: provider response failed\n"
                "Vulnerabilities 9\n"
            )
        )


if __name__ == "__main__":
    unittest.main()
