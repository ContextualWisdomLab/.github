"""Regression contract for strix-agent's recovered transient model errors.

strix-agent 1.5.3 (``strix/core/execution.py:760-763``) retries a transient
model/provider error up to ``_MAX_TRANSIENT_MODEL_RETRIES`` times and, inside
that branch only, logs::

    WARNING <run> - strix.core.execution: transient model/provider error for
    <agent>; replaying turn (attempt n/m, backoff Ns): <exception repr>

immediately before the replay runs. The line therefore means "a retry is
happening now", never "the scan failed". When the budget is exhausted the same
module logs ``agent run failed for <agent>; marking failed`` at ERROR with a
traceback and the process exits non-zero.

The raw retry warning is retained. A separate current-attempt classifier may
accept it only beside a new completed/successful run receipt and valid SARIF.
This keeps malformed receipts and exhausted ``attempt n/n`` warnings fail-closed
instead of deleting the evidence before classification.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_GATE = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"

_PREFIX = "strix-pr-scope-qd1fsv_9ee6 - strix.core.execution: "

# The three lines exactly as the run above wrote them (490 characters each).
_REPR = (
    "InternalServerError(\"Error code: 500 - {'error': {'code': 'internal_error', "
    "'message': 'internal server error', 'detail': {'request_id': '%s'}}, "
    "'error_code': 'internal_error', 'error_message': 'internal server error', "
    "'error_detail': {'request_id': '%s'}}\")"
)
RECOVERED_LOG = (
    "2026-09-06 07:23:08.199 WARNING " + _PREFIX
    + "transient model/provider error for 76d3c83d; replaying turn "
    "(attempt 1/5, backoff 2.0s): "
    + _REPR % ("466c7aee94e24a6e811cbd7fd12bc1a9", "466c7aee94e24a6e811cbd7fd12bc1a9")
    + "\n"
    "2026-09-06 07:23:10.205 DEBUG   strix-pr-scope-qd1fsv_9ee6 - "
    "strix.llm.context_budget: No LiteLLM model info for 'openai/orchestrator/free'; "
    "using configured fallbacks\n"
    "2026-09-06 07:45:20.154 WARNING " + _PREFIX
    + "transient model/provider error for 76d3c83d; replaying turn "
    "(attempt 2/5, backoff 4.0s): "
    + _REPR % ("6dbf7b28ee16448592e10bb9728a523f", "6dbf7b28ee16448592e10bb9728a523f")
    + "\n"
    "2026-09-06 07:58:54.623 WARNING " + _PREFIX
    + "transient model/provider error for 76d3c83d; replaying turn "
    "(attempt 3/5, backoff 8.0s): "
    + _REPR % ("a85b9828eb754e129f62d202359ea316", "a85b9828eb754e129f62d202359ea316")
    + "\n"
    "2026-09-06 08:09:35.584 INFO    strix-pr-scope-qd1fsv_9ee6 - "
    "strix.core.runner: Strix scan strix-pr-scope-qd1fsv_9ee6 done\n"
)

# After the bounded budget is spent strix-agent logs at ERROR with a traceback
# (observed on a same-day run) and exits non-zero. The sanitizer must leave it.
UNRECOVERED_LOG = (
    "2026-09-06 07:24:31.010 WARNING strix-pr-scope-5p3h3c_e0d0 - "
    "strix.core.execution: transient model/provider error for 6c480eb0; "
    "replaying turn (attempt 5/5, backoff 32.0s): InternalServerError(\"Error code: 500\")\n"
    "2026-09-06 07:24:40.562 ERROR   strix-pr-scope-5p3h3c_e0d0 - "
    "strix.core.execution: agent run failed for 6c480eb0; marking failed\n"
    "Traceback (most recent call last):\n"
    '  File "/opt/hostedtoolcache/Python/3.13.15/x64/lib/python3.13/site-packages/'
    'strix/core/execution.py", line 676, in _run_cycle\n'
    "    async for event in stream.stream_events():\n"
    "openai.InternalServerError: Error code: 500\n"
)

UNKNOWN_WARNING_LOG = (
    "2026-09-06 07:30:00.000 WARNING strix-pr-scope-qd1fsv_9ee6 - "
    "strix.core.execution: transient model/provider error for 76d3c83d; "
    "giving up after 5 attempts\n"
)

# A different module echoing the same words must not be sanitized: the anchor
# is the logger name, not the phrase.
FOREIGN_MODULE_LOG = (
    "2026-09-06 07:30:00.000 WARNING strix-pr-scope-qd1fsv_9ee6 - "
    "strix.tools.browser: transient model/provider error for 76d3c83d; "
    "replaying turn (attempt 1/5, backoff 2.0s): Timeout\n"
)

LEGACY_LOG = (
    "2026-06-18 13:08:05.986 WARNING strix-pr-scope-example - strix.core.execution: "
    "agent a9fb4033 produced non-lifecycle final output in non-interactive mode; "
    "forcing tool continuation (1/3): {'x': 1}\n"
    "2026-08-22 09:53:26.193 WARNING strix-pr-scope-example - strix.core.execution: "
    "agent 673f770f ended a turn without a lifecycle tool call (interactive=False); "
    "forcing tool continuation (2/3): done\n"
    "2026-06-18 13:10:44.089 INFO    strix-pr-scope-example - strix.tools.finish.tool: "
    "finish_scan: completed scan with 0 vulnerability report(s)\n"
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


def _sanitize_then_signal(log_text: str) -> tuple[str, bool]:
    """Run the production sanitizer, then the production failure-signal scan.

    Returns the report log's remaining text and whether
    ``has_strix_report_failure_signal`` still fires on it. The report root is a
    plain temp directory, so the function's ``STRIX_REPORTS_DIR`` branch
    (which resolves the newest run) is not taken and needs no helper.
    """

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    blocks = [
        _function_block(gate_source, name)
        for name in (
            "sanitize_known_strix_report_warnings",
            "strix_report_has_authoritative_recovered_transient_completion",
            "has_strix_report_failure_signal",
        )
    ]
    with tempfile.TemporaryDirectory(prefix="strix-recovered-transient-") as temp_dir:
        report_root = Path(temp_dir) / "strix_runs" / "strix-pr-scope-qd1fsv_9ee6"
        report_root.mkdir(parents=True)
        log_path = report_root / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -uo pipefail",
                'STRIX_REPORTS_DIR="/nonexistent/strix-reports"',
                'STRIX_LOG="$1/strix.log"',
                "declare -A ATTEMPT_START_RUN_RECORD_DIGESTS=()",
                *blocks,
                'sanitize_known_strix_report_warnings "$1"',
                'if has_strix_report_failure_signal "$1"; then echo signal=1; else echo signal=0; fi',
            )
        )
        completed = subprocess.run(
            ["bash", "-c", script, "strix-sanitizer", str(report_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        remaining = log_path.read_text(encoding="utf-8")
    if completed.returncode != 0:
        raise AssertionError(f"rc={completed.returncode}\n{completed.stderr}")
    return remaining, "signal=1" in completed.stdout


def _sanitize_then_signal_production_shape(log_text: str) -> tuple[str, bool]:
    """Same sequence with the argument shape production actually uses.

    Production passes ``ACTIVE_REPORTS_DIR``, which equals ``STRIX_REPORTS_DIR``,
    so ``has_strix_report_failure_signal`` takes its narrowing branch and scans
    only ``latest_strix_report_dir``'s newest run directory. ``_sanitize_then_signal``
    hands in that run directory directly and therefore skips the branch; this
    helper covers it, so the pair proves the sanitized tree and the scanned tree
    are the same one.
    """

    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    blocks = [
        _function_block(gate_source, name)
        for name in (
            "sanitize_known_strix_report_warnings",
            "strix_report_has_authoritative_recovered_transient_completion",
            "has_strix_report_failure_signal",
            "latest_strix_report_dir",
            "is_preexisting_report_dir",
        )
    ]
    with tempfile.TemporaryDirectory(prefix="strix-recovered-transient-prod-") as temp_dir:
        reports_root = Path(temp_dir) / "reports"
        run_dir = reports_root / "strix-pr-scope-qd1fsv_9ee6"
        run_dir.mkdir(parents=True)
        log_path = run_dir / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -uo pipefail",
                f'STRIX_REPORTS_DIR="{reports_root}"',
                f'STRIX_LOG="{log_path}"',
                "declare -A ATTEMPT_START_RUN_RECORD_DIGESTS=()",
                # Non-empty so "${PREEXISTING_REPORT_DIRS[@]}" is safe under set -u.
                'PREEXISTING_REPORT_DIRS=("/nonexistent/preexisting")',
                *blocks,
                'sanitize_known_strix_report_warnings "$STRIX_REPORTS_DIR"',
                'if has_strix_report_failure_signal "$STRIX_REPORTS_DIR"; then echo signal=1; else echo signal=0; fi',
            )
        )
        completed = subprocess.run(
            ["bash", "-c", script, "strix-sanitizer-prod"],
            check=False,
            capture_output=True,
            text=True,
        )
        remaining = log_path.read_text(encoding="utf-8")
    if completed.returncode != 0:
        raise AssertionError(f"rc={completed.returncode}\n{completed.stderr}")
    return remaining, "signal=1" in completed.stdout


class StrixRecoveredTransientSanitizerTests(unittest.TestCase):
    """Retain transient evidence until structured classification."""

    def test_recovered_transient_replay_warnings_remain_without_receipts(self) -> None:
        """A warning alone is not enough to prove the retry recovered."""

        remaining, signal = _sanitize_then_signal(RECOVERED_LOG)
        self.assertIn("replaying turn", remaining)
        self.assertIn("InternalServerError", remaining)
        self.assertIn("strix.core.runner: Strix scan strix-pr-scope-qd1fsv_9ee6 done", remaining)
        self.assertIn("strix.llm.context_budget", remaining)
        self.assertTrue(signal)

    def test_unrecovered_transient_keeps_the_error_and_traceback(self) -> None:
        """An exhausted retry keeps its warning, error, and traceback."""

        remaining, signal = _sanitize_then_signal(UNRECOVERED_LOG)
        self.assertIn("replaying turn", remaining)
        self.assertIn("agent run failed for 6c480eb0; marking failed", remaining)
        self.assertIn("Traceback (most recent call last):", remaining)
        self.assertIn("openai.InternalServerError: Error code: 500", remaining)
        self.assertTrue(signal)

    def test_unknown_execution_warning_still_fails_closed(self) -> None:
        """A WARNING from the same logger with a different message is not sanitized."""

        remaining, signal = _sanitize_then_signal(UNKNOWN_WARNING_LOG)
        self.assertEqual(remaining, UNKNOWN_WARNING_LOG)
        self.assertTrue(signal)

    def test_same_words_from_another_module_still_fail_closed(self) -> None:
        """The anchor is the strix.core.execution logger, not the phrase."""

        remaining, signal = _sanitize_then_signal(FOREIGN_MODULE_LOG)
        self.assertEqual(remaining, FOREIGN_MODULE_LOG)
        self.assertTrue(signal)

    def test_production_shape_keeps_warning_without_structured_receipts(self) -> None:
        """The production narrowing branch retains unproven retry evidence."""

        remaining, signal = _sanitize_then_signal_production_shape(RECOVERED_LOG)
        self.assertIn("replaying turn", remaining)
        self.assertIn("strix.core.runner: Strix scan strix-pr-scope-qd1fsv_9ee6 done", remaining)
        self.assertTrue(signal)

    def test_production_argument_shape_still_fails_closed_on_an_unknown_warning(self) -> None:
        """The narrowing branch does not swallow a warning the sanitizer does not know."""

        remaining, signal = _sanitize_then_signal_production_shape(UNKNOWN_WARNING_LOG)
        self.assertEqual(remaining, UNKNOWN_WARNING_LOG)
        self.assertTrue(signal)

    def test_existing_forced_continuation_warnings_remain_sanitized(self) -> None:
        """The two pre-existing alternatives keep working after the regex restructure."""

        remaining, signal = _sanitize_then_signal(LEGACY_LOG)
        self.assertNotIn("forcing tool continuation", remaining)
        self.assertIn("finish_scan: completed scan with 0 vulnerability report(s)", remaining)
        self.assertFalse(signal)


if __name__ == "__main__":
    unittest.main()
