"""Regression contract for GitHub Models retirement-brownout fallback.

Required Strix runs observed `Error code: 410` with
`github_models_retirement_brownout` after NVIDIA NIM attempts exhausted the
90-minute process budget. The gate must treat that provider-family outage as
cross-model skip evidence, keep a reserved NVIDIA NIM process cap so later
hosted candidates still run, and refuse to classify application 410 text or
cross-line spoofing as infrastructure.
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
OBSERVED_BROWNOUT_LINE = (
    "openai.APIStatusError: Error code: 410 - {'error': {'code': "
    "'github_models_retirement_brownout', 'message': 'GitHub Models is "
    "temporarily unavailable as part of a scheduled retirement brownout.'}}\n"
)
SECOND_NVIDIA_FALLBACK = "nvidia_nim/nvidia/llama-3.1-nemotron-ultra-253b-v1"


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace."""

    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) {{\n.*?^}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _classifies_as_retirement_brownout(log_text: str) -> bool:
    """Execute the production brownout classifier against a synthetic log."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    function_source = _function_block(
        gate_source,
        "is_github_models_retirement_brownout_error",
    )
    with tempfile.TemporaryDirectory(prefix="strix-gh-410-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -euo pipefail",
                'STRIX_LOG="$1"',
                function_source,
                "is_github_models_retirement_brownout_error",
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


class StrixGithubModelsRetirementBrownoutTests(unittest.TestCase):
    """Protect family-level 410 skip without weakening security evidence."""

    def test_observed_github_models_410_is_retryable_provider_evidence(self) -> None:
        """Recognize the exact required-CI retirement brownout line."""

        self.assertTrue(_classifies_as_retirement_brownout(OBSERVED_BROWNOUT_LINE))

    def test_application_410_without_github_models_context_is_not_retryable(
        self,
    ) -> None:
        """Do not let target-application HTTP 410 text skip fallbacks."""

        log = "GET /api/project_record/retired 410\nGone: archive missing\n"
        self.assertFalse(_classifies_as_retirement_brownout(log))

    def test_provider_and_410_signals_must_share_one_log_line(self) -> None:
        """Reject cross-line assembly from untrusted scan-target output."""

        log = (
            "source literal: GitHub Models\n"
            "GET /api/project_record/retired Error code: 410\n"
        )
        self.assertFalse(_classifies_as_retirement_brownout(log))

    def test_brownout_code_without_410_status_is_not_enough(self) -> None:
        """Require the HTTP 410 or retirement phrase on the same line."""

        log = "github_models_retirement_brownout scheduled later for GitHub Models\n"
        self.assertFalse(_classifies_as_retirement_brownout(log))

    def test_issue_number_410_on_a_brownout_line_is_not_family_dead(self) -> None:
        """A SHA or issue #410 is not HTTP 410 (CWE-1288)."""

        log = (
            "github_models_retirement_brownout for GitHub Models; see issue #410\n"
        )
        self.assertFalse(_classifies_as_retirement_brownout(log))
        self.assertTrue(
            _classifies_as_retirement_brownout(
                "GitHub Models HTTP 410 github_models_retirement_brownout\n"
            )
        )

    def test_longer_status_codes_that_start_with_410_are_not_family_dead(
        self,
    ) -> None:
        """HTTP 4100 or Error code: 4104 must not match the retirement 410."""

        self.assertFalse(
            _classifies_as_retirement_brownout(
                "GitHub Models Error code: 4100 "
                "github_models_retirement_brownout\n"
            )
        )
        self.assertFalse(
            _classifies_as_retirement_brownout(
                "GitHub Models HTTP 4104 github_models_retirement_brownout\n"
            )
        )
        self.assertTrue(
            _classifies_as_retirement_brownout(
                "GitHub Models Error code: 410 "
                "github_models_retirement_brownout\n"
            )
        )

    def test_brownout_enters_infrastructure_and_unavailable_model_paths(
        self,
    ) -> None:
        """Wire the classifier into family skip, not same-model retry."""

        gate_source = STRIX_GATE.read_text(encoding="utf-8")
        infrastructure = _function_block(
            gate_source,
            "has_detected_infrastructure_error",
        )
        unavailable = _function_block(
            gate_source,
            "is_github_models_unavailable_model_error",
        )
        same_model_retry = _function_block(
            gate_source,
            "is_transient_same_model_retry_error",
        )
        run_once = _function_block(gate_source, "run_strix_once")
        current_scan = _function_block(gate_source, "run_current_target_scan")

        self.assertIn("is_github_models_retirement_brownout_error", infrastructure)
        self.assertIn("is_github_models_retirement_brownout_error", unavailable)
        self.assertNotIn(
            "is_github_models_retirement_brownout_error",
            same_model_retry,
        )
        self.assertIn("is_nvidia_nim_model", run_once)
        self.assertIn("STRIX_NVIDIA_NIM_PROCESS_TIMEOUT_SECONDS", run_once)
        self.assertIn("skip_remaining_github_models", current_scan)

    def test_workflow_reserves_nim_budget_and_second_hosted_candidate(self) -> None:
        """Keep two NVIDIA hosted candidates before retired GitHub Models."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('nim_process_budget_seconds="1800"', workflow)
        self.assertIn(SECOND_NVIDIA_FALLBACK, workflow)
        self.assertIn("github_models_retirement_brownout", workflow)
        self.assertNotIn("STRIX_NVIDIA_NIM_PROCESS_TIMEOUT_SECONDS:", workflow)


if __name__ == "__main__":
    unittest.main()
