"""Regression contract for the strix-agent Caido sandbox bootstrap timing race.

Upstream strix-agent (usestrix/strix#1036, #1037, #1056) runs a chown -R on
the sandbox container before starting caido-cli, and enforces a fixed
10-attempt loginAsGuest retry budget. A slow CI runner can exceed that
budget before the local proxy is reachable, even though the penetration
test itself never started and no security evidence was produced or lost.
This is local sandbox/container boot timing, not tied to any one LLM model,
so it must be retried same-model rather than treated as grounds to switch
models or as a genuine, non-backend scan failure.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_GATE = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"

# The exact strings strix-agent's caido_bootstrap.py emits on this failure.
OBSERVED_LOG = (
    "Error during penetration test: loginAsGuest failed after 10 attempts: "
    "curl exit 7: curl: (7) Failed to connect to 127.0.0.1 port 48080 after "
    "0 ms: Could not connect to server\n"
    "Vulnerabilities 0\n"
)


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace."""

    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _classifies_as_caido_bootstrap_timing(log_text: str) -> bool:
    """Execute the production classifier against a bounded synthetic log."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    function_source = _function_block(
        gate_source,
        "is_caido_bootstrap_timing_error",
    )
    with tempfile.TemporaryDirectory(prefix="strix-caido-timing-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -euo pipefail",
                'STRIX_LOG="$1"',
                function_source,
                "is_caido_bootstrap_timing_error",
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


class StrixCaidoBootstrapTimingRetryTests(unittest.TestCase):
    """Protect same-model retry for the upstream sandbox boot race."""

    def test_observed_caido_login_failure_is_retryable(self) -> None:
        """Recognize the exact loginAsGuest failure observed in required CI."""

        self.assertTrue(_classifies_as_caido_bootstrap_timing(OBSERVED_LOG))

    def test_different_port_is_still_recognized(self) -> None:
        """Match the strix-agent message shape, not one hardcoded port."""

        log = (
            "loginAsGuest failed after 10 attempts: curl exit 7: curl: (7) "
            "Failed to connect to 127.0.0.1 port 51234 after 0 ms: Could "
            "not connect to server\n"
        )
        self.assertTrue(_classifies_as_caido_bootstrap_timing(log))

    def test_unrelated_connection_refused_is_not_retryable(self) -> None:
        """Do not let an unrelated target-application connection error match."""

        log = "requests.exceptions.ConnectionError: Failed to establish a new connection\n"
        self.assertFalse(_classifies_as_caido_bootstrap_timing(log))

    def test_login_failure_without_the_connect_evidence_is_not_retryable(self) -> None:
        """Require both the loginAsGuest phrase and the connect-failure line."""

        log = "loginAsGuest failed after 10 attempts: unknown reason\n"
        self.assertFalse(_classifies_as_caido_bootstrap_timing(log))

    def test_wired_into_same_model_retry_and_infrastructure_not_cross_model(
        self,
    ) -> None:
        """Retry the same model; do not treat this as a reason to switch models.

        Switching LLM models cannot change how long the local sandbox
        container takes to boot, so cross-model fallback (`is_model_retryable_error`)
        must stay untouched by this classifier.
        """

        gate_source = STRIX_GATE.read_text(encoding="utf-8")
        infrastructure = _function_block(
            gate_source,
            "has_detected_infrastructure_error",
        )
        same_model_retry = _function_block(
            gate_source,
            "is_transient_same_model_retry_error",
        )
        cross_model_retry = _function_block(gate_source, "is_model_retryable_error")

        self.assertIn("is_caido_bootstrap_timing_error", infrastructure)
        self.assertIn("is_caido_bootstrap_timing_error", same_model_retry)
        self.assertNotIn("is_caido_bootstrap_timing_error", cross_model_retry)

    def test_retry_reason_is_logged_for_operators(self) -> None:
        """Keep the diagnostic retry-reason message in sync with the classifier."""

        gate_source = STRIX_GATE.read_text(encoding="utf-8")
        self.assertIn(
            'retry_reason="Caido sandbox bootstrap timing"',
            gate_source,
        )


if __name__ == "__main__":
    unittest.main()
