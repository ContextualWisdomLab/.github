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

OPTIONAL_SEARCH_WARNING = (
    "2026-09-12 12:30:48.087 WARNING strix-pr-scope-vjsusm_b6ed - "
    "strix.tools.web_search.tool: web_search invoked without PERPLEXITY_API_KEY configured\n"
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
    def test_missing_optional_perplexity_key_does_not_fail_completed_scan(self) -> None:
        remaining, signal = _sanitize_then_signal(OPTIONAL_SEARCH_WARNING + COMPLETION_LINE)
        self.assertNotIn("web_search invoked without PERPLEXITY_API_KEY configured", remaining)
        self.assertIn("Strix scan strix-pr-scope-vjsusm_b6ed done", remaining)
        self.assertFalse(signal)

    def test_unknown_web_search_warning_remains_fail_closed(self) -> None:
        remaining, signal = _sanitize_then_signal(UNKNOWN_SEARCH_WARNING + COMPLETION_LINE)
        self.assertIn("provider returned malformed search evidence", remaining)
        self.assertTrue(signal)


if __name__ == "__main__":
    unittest.main()
