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


RATE_LIMIT_LOG = (
    "litellm.RateLimitError: RateLimitError: rate limit exceeded\n"
    "Vulnerabilities 0\n"
)


def _run_retry_loop(log_text: str, *, per_model: int, sandbox_retries: int) -> tuple[int, str]:
    """Drive the production retry loop with a stubbed Strix run and return (calls, stderr).

    The reported sandbox retry count (``SANDBOX_RETRIES_USED``) is echoed to
    stdout as ``reported=<n>`` and appended to the returned stderr text so
    tests can assert it without a second harness.

    ``run_strix_once`` is replaced by a stub that writes ``log_text`` to the
    attempt log and fails, so the loop's own retry decision is what is under
    test; every classifier the loop consults is the production function.
    """

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    blocks = [
        _function_block(gate_source, name)
        for name in (
            "run_strix_with_transient_retry",
            "is_transient_same_model_retry_error",
            "is_timeout_error",
            "is_llm_api_connection_error",
            "is_llm_service_unavailable_error",
            "is_rate_limit_error",
            "is_midstream_fallback_error",
            "is_caido_bootstrap_timing_error",
        )
    ]
    with tempfile.TemporaryDirectory(prefix="strix-caido-retry-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        counter = Path(temp_dir) / "calls"
        counter.write_text("0", encoding="utf-8")
        script = "\n".join(
            (
                "set -uo pipefail",
                f'STRIX_LOG="{log_path}"',
                f'COUNTER="{counter}"',
                f"STRIX_TRANSIENT_RETRY_PER_MODEL={per_model}",
                f"STRIX_SANDBOX_BOOTSTRAP_RETRIES={sandbox_retries}",
                "STRIX_TRANSIENT_RETRY_BACKOFF_SECONDS=0",
                "STRIX_TOTAL_TIMEOUT_SECONDS=0",
                "TOTAL_TIMEOUT_EXCEEDED=0",
                "github_models_rate_limit_should_skip_same_model_retry() { return 1; }",
                # The stub caps itself: a runaway loop returns the configuration
                # exit code 2 after six calls, which the harness reports as a
                # failure instead of hanging the suite.
                'run_strix_once() { n=$(( $(cat "$COUNTER") + 1 )); echo "$n" > "$COUNTER"; printf "%s" "$LOG_TEXT" > "$STRIX_LOG"; [ "$n" -ge 6 ] && return 2; return 1; }',
                *blocks,
                'run_strix_with_transient_retry "orchestrator/free"; rc=$?; echo "reported=$SANDBOX_RETRIES_USED"; exit "$rc"',
            )
        )
        completed = subprocess.run(
            ["bash", "-c", script, "strix-retry"],
            check=False,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin", "LOG_TEXT": log_text},
        )
        calls = int(counter.read_text(encoding="utf-8").strip())
    if completed.returncode != 1:
        raise AssertionError(f"rc={completed.returncode}\n{completed.stderr}")
    return calls, completed.stderr + completed.stdout


def _orchestrator_verdict_line(log_text: str) -> str:
    """Return the stderr the primary-scan verdict branch emits for a failed orchestrator scan."""

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    blocks = [
        _function_block(gate_source, name)
        for name in ("run_current_target_scan", "is_caido_bootstrap_timing_error")
    ]
    with tempfile.TemporaryDirectory(prefix="strix-caido-verdict-") as temp_dir:
        log_path = Path(temp_dir) / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -uo pipefail",
                f'STRIX_LOG="{log_path}"',
                'PRIMARY_MODEL="orchestrator/free"',
                "STRIX_SANDBOX_BOOTSTRAP_RETRIES=1",
                "SANDBOX_RETRIES_USED=1",
                "TOTAL_TIMEOUT_EXCEEDED=0",
                # run_current_target_scan resets INFRA_ERROR_DETECTED before the
                # scan; the production run_strix_once sets it on a failed attempt,
                # so the stub does the same.
                "run_strix_with_transient_retry() { INFRA_ERROR_DETECTED=1; return 1; }",
                "provider_signal_fail_closed_enabled() { return 0; }",
                "is_contextual_orchestrator_model() { return 0; }",
                "is_model_retryable_error() { return 1; }",
                "has_distinct_fallback_model_for_model() { return 1; }",
                # has_detected_infrastructure_error is consulted by run_strix_once,
                # which the stub above replaces; the flag is set by that path.
                *blocks,
                "run_current_target_scan",
            )
        )
        completed = subprocess.run(
            ["bash", "-c", script, "strix-verdict"],
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode != 1:
        raise AssertionError(f"rc={completed.returncode}\n{completed.stderr}")
    return completed.stderr


class StrixSandboxBootstrapRetryAndVerdictTests(unittest.TestCase):
    """The sandbox race gets its own bounded retry and its own name in the verdict.

    Evidence (2026-09-06): ``argos`` Strix run 34013128112 and a second
    artifact both show a single attempt ending in ``loginAsGuest failed after
    10 attempts`` on ``127.0.0.1:48080`` after ``Docker image ready``, then
    ``STRIX_PROVIDER_UNAVAILABLE: … orchestrator/free exhausted`` -- while the
    sidecar had four ready and four deferred routes that were never called.
    ``STRIX_TRANSIENT_RETRY_PER_MODEL`` defaults to 0 and the workflow does not
    raise it, so the documented same-model retry for this class never ran.
    """

    def test_sandbox_bootstrap_failure_is_retried_once_even_with_zero_per_model_budget(self) -> None:
        calls, stderr = _run_retry_loop(OBSERVED_LOG, per_model=0, sandbox_retries=1)
        self.assertEqual(calls, 2)
        self.assertIn("Caido sandbox bootstrap timing", stderr)
        self.assertIn("attempt 2/2", stderr)

    def test_sandbox_retry_budget_is_bounded(self) -> None:
        calls, _ = _run_retry_loop(OBSERVED_LOG, per_model=0, sandbox_retries=2)
        self.assertEqual(calls, 3)
        calls, _ = _run_retry_loop(OBSERVED_LOG, per_model=0, sandbox_retries=0)
        self.assertEqual(calls, 1)

    def test_mixed_sandbox_and_gateway_log_stays_bounded(self) -> None:
        """A log matching the sandbox class AND a gateway class grants at most the sandbox budget.

        Found by adversarial review of the first draft, which charged the
        sandbox counter in the retry-reason chain behind the gateway classes:
        such a log then extended the budget on every iteration without ever
        charging it, and production bounds the loop with nothing but GitHub's
        six-hour default.
        """

        calls, stderr = _run_retry_loop(RATE_LIMIT_LOG + OBSERVED_LOG, per_model=0, sandbox_retries=1)
        self.assertEqual(calls, 2)
        self.assertNotIn("attempt 3/", stderr)

    def test_sandbox_budget_is_granted_on_top_of_the_per_model_budget(self) -> None:
        calls, _ = _run_retry_loop(OBSERVED_LOG, per_model=1, sandbox_retries=1)
        self.assertEqual(calls, 3)

    def test_reported_sandbox_retries_count_only_retries_that_ran(self) -> None:
        """A granted attempt vetoed by the timeout check is not reported as a retry.

        Lane peer 1's verification note: the budget is charged at the grant,
        but ``is_transient_same_model_retry_error`` returns 1 for a timeout
        signature, so a log carrying both the sandbox and a timeout signature
        is granted, charged, and then not retried; the verdict must say 0.
        """

        calls, out = _run_retry_loop(
            "litellm.exceptions.Timeout: request timed out\n" + OBSERVED_LOG,
            per_model=0,
            sandbox_retries=1,
        )
        self.assertEqual(calls, 1)
        self.assertIn("reported=0", out)
        calls, out = _run_retry_loop(OBSERVED_LOG, per_model=0, sandbox_retries=1)
        self.assertEqual(calls, 2)
        self.assertIn("reported=1", out)

    def test_sandbox_retry_does_not_widen_gateway_retries(self) -> None:
        """A rate limit from the gateway still gets no same-model retry at budget 0."""

        calls, stderr = _run_retry_loop(RATE_LIMIT_LOG, per_model=0, sandbox_retries=1)
        self.assertEqual(calls, 1)
        self.assertNotIn("Retrying model", stderr)

    def test_verdict_names_the_sandbox_and_keeps_the_workflow_token(self) -> None:
        stderr = _orchestrator_verdict_line(OBSERVED_LOG)
        self.assertIn("STRIX_PROVIDER_UNAVAILABLE: STRIX_SANDBOX_UNAVAILABLE:", stderr)
        self.assertIn("after 1 sandbox-specific same-model retries (budget 1)", stderr)
        self.assertIn("names Strix's sandbox, not the LLM gateway", stderr)
        self.assertNotIn("orchestrator/free exhausted", stderr)

    def test_verdict_for_a_gateway_failure_is_unchanged(self) -> None:
        stderr = _orchestrator_verdict_line(RATE_LIMIT_LOG)
        self.assertIn("orchestrator/free exhausted", stderr)
        self.assertNotIn("STRIX_SANDBOX_UNAVAILABLE", stderr)


if __name__ == "__main__":
    unittest.main()
