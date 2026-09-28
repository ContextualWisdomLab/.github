"""Regression for Strix's optional web-search capability warning.

Strix documents PERPLEXITY_API_KEY as optional and its web-search tool returns a
sanitized ``success: false`` result instructing the agent to proceed when the
key is absent. A completed scan must therefore not be reclassified as provider
unavailability solely because that exact warning appears in ``strix.log``.
Unknown warnings remain fail-closed.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_GATE = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"
CHANGELOG_FRAGMENT = (
    REPOSITORY_ROOT
    / "CHANGELOG.d"
    / "20260912-strix-optional-web-search-warning.md"
)

OPTIONAL_SEARCH_KEY_LABELS = (
    "EXA_API_KEY",
    "PERPLEXITY_API_KEY",
    "EXA_API_KEY or PERPLEXITY_API_KEY",
)
UNKNOWN_SEARCH_WARNING = (
    "2026-09-12 12:30:48.087 WARNING strix-pr-scope-vjsusm_b6ed - "
    "strix.tools.web_search.tool: provider returned malformed search evidence\n"
)
COMPLETION_LINE = (
    "2026-09-12 12:45:56.390 INFO    strix-pr-scope-vjsusm_b6ed - "
    "strix.core.runner: Strix scan strix-pr-scope-vjsusm_b6ed done\n"
)


def _function_block(source: str, function_name: str) -> str:
    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _sanitize_then_signal(log_text: str) -> tuple[str, bool]:
    gate_source = STRIX_GATE.read_text(encoding="utf-8")
    blocks = [
        _function_block(gate_source, name)
        for name in (
            "sanitize_known_strix_report_warnings",
            "has_strix_report_failure_signal",
        )
    ]
    with tempfile.TemporaryDirectory(prefix="strix-optional-search-") as temp_dir:
        report_root = Path(temp_dir) / "run"
        report_root.mkdir()
        log_path = report_root / "strix.log"
        log_path.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -uo pipefail",
                'STRIX_REPORTS_DIR="/nonexistent/strix-reports"',
                *blocks,
                'sanitize_known_strix_report_warnings "$1"',
                'if has_strix_report_failure_signal "$1"; then echo signal=1; else echo signal=0; fi',
            )
        )
        completed = subprocess.run(
            ["bash", "-c", script, "strix-optional-search", str(report_root)],
            check=False,
            capture_output=True,
            text=True,
        )
        remaining = log_path.read_text(encoding="utf-8")
    if completed.returncode != 0:
        raise AssertionError(f"rc={completed.returncode}\n{completed.stderr}")
    return remaining, "signal=1" in completed.stdout


class StrixOptionalWebSearchWarningTests(unittest.TestCase):
    def test_changelog_describes_sanitized_classification_log(self) -> None:
        changelog_text = CHANGELOG_FRAGMENT.read_text(encoding="utf-8")
        self.assertIn("classification log", changelog_text)
        self.assertNotIn("raw report artifacts remain unchanged", changelog_text)

    def test_missing_optional_search_keys_do_not_fail_completed_scan(self) -> None:
        for search_key_label in OPTIONAL_SEARCH_KEY_LABELS:
            with self.subTest(search_key_label=search_key_label):
                optional_search_warning = (
                    "2026-09-12 12:30:48.087 WARNING strix-pr-scope-vjsusm_b6ed - "
                    "strix.tools.web_search.tool: web_search invoked without "
                    f"{search_key_label} configured\n"
                )
                remaining, signal = _sanitize_then_signal(
                    optional_search_warning + COMPLETION_LINE
                )
                self.assertNotIn(
                    f"web_search invoked without {search_key_label} configured",
                    remaining,
                )
                self.assertIn("Strix scan strix-pr-scope-vjsusm_b6ed done", remaining)
                self.assertFalse(signal)

    def test_unknown_web_search_warning_remains_fail_closed(self) -> None:
        remaining, signal = _sanitize_then_signal(UNKNOWN_SEARCH_WARNING + COMPLETION_LINE)
        self.assertIn("provider returned malformed search evidence", remaining)
        self.assertTrue(signal)

    def test_completed_scan_ignores_only_exact_pty_count_notice(self) -> None:
        notice = "PTY process count reached warning threshold: 60 active sessions\n"
        remaining, signal = _sanitize_then_signal(notice + COMPLETION_LINE)
        self.assertNotIn(notice, remaining)
        self.assertFalse(signal)

        unknown = "PTY process count reached warning threshold: unknown active sessions\n"
        remaining, signal = _sanitize_then_signal(unknown + COMPLETION_LINE)
        self.assertIn(unknown, remaining)
        self.assertTrue(signal)

    def test_pty_notice_does_not_trigger_console_infrastructure_error(self) -> None:
        gate_source = STRIX_GATE.read_text(encoding="utf-8")
        blocks = [
            _function_block(gate_source, name)
            for name in (
                "sanitize_known_strix_report_warnings",
                "has_detected_infrastructure_error",
            )
        ]
        with tempfile.TemporaryDirectory(prefix="strix-pty-console-") as temp_dir:
            log_path = Path(temp_dir) / "console.log"
            script = "\n".join(
                (
                    "set -uo pipefail",
                    'STRIX_LOG="$1"',
                    'LLM_PROVIDER_ONLY_REGEX="__never__"',
                    "for name in is_timeout_error is_rate_limit_error is_llm_token_limit_error is_midstream_fallback_error is_llm_api_connection_error is_llm_service_unavailable_error is_nvidia_nim_not_found_error is_model_behavior_error is_caido_bootstrap_timing_error; do eval \"$name() { return 1; }\"; done",
                    *blocks,
                    'sanitize_known_strix_report_warnings "$STRIX_LOG"',
                    'if has_detected_infrastructure_error; then echo signal=1; else echo signal=0; fi',
                )
            )
            for notice, expected in (
                ("PTY process count reached warning threshold: 60 active sessions\n", False),
                ("PTY process count reached warning threshold: unknown active sessions\n", True),
            ):
                log_path.write_text(notice + COMPLETION_LINE, encoding="utf-8")
                completed = subprocess.run(
                    ["bash", "-c", script, "strix-pty-console", str(log_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual("signal=1" in completed.stdout, expected)


if __name__ == "__main__":
    unittest.main()
