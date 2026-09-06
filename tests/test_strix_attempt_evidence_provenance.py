"""Attempt-scoped Strix evidence must be classified by provenance and content."""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_GATE = REPOSITORY_ROOT / "scripts" / "ci" / "strix_quick_gate.sh"


def _function_block(source: str, function_name: str) -> str:
    """Return one top-level Bash function, including its closing brace."""

    match = re.search(
        rf"(?ms)^{re.escape(function_name)}\(\) \{{\n.*?^\}}\n",
        source,
    )
    if match is None:
        raise AssertionError(f"missing Bash function: {function_name}")
    return match.group(0)


def _optional_function_block(source: str, function_name: str) -> str:
    """Return a function when present, allowing the pre-fix RED to execute."""

    try:
        return _function_block(source, function_name)
    except AssertionError:
        return ""


def _vulnerability_artifact_is_new(*, rewrite: bytes | None) -> bool:
    """Replay the production snapshot/predicate around an in-place report write."""

    source = STRIX_GATE.read_text(encoding="utf-8")
    blocks = [
        _optional_function_block(source, "strix_vulnerability_report_digest"),
        _function_block(source, "capture_attempt_start_vulnerability_files"),
        _function_block(source, "is_attempt_start_vulnerability_file"),
        _function_block(source, "is_preexisting_report_dir"),
        _function_block(source, "has_new_strix_vulnerability_report_artifact"),
    ]
    with tempfile.TemporaryDirectory(prefix="strix-vulnerability-provenance-") as temp:
        reports = Path(temp) / "reports"
        vulnerability = reports / "current-run" / "vulnerabilities" / "vuln-0001.md"
        vulnerability.parent.mkdir(parents=True)
        original = b"# Finding\n\nSeverity: INFO\nAttempt: first\n"
        vulnerability.write_bytes(original)
        script = "\n".join(
            (
                "set -euo pipefail",
                'STRIX_REPORTS_DIR="$1"',
                'VULNERABILITY_PATH="$2"',
                'REWRITE_PATH="$3"',
                'PREEXISTING_REPORT_DIRS=("/nonexistent/preexisting")',
                "ATTEMPT_START_VULNERABILITY_FILES=()",
                "declare -A ATTEMPT_START_VULNERABILITY_DIGESTS=()",
                *blocks,
                "capture_attempt_start_vulnerability_files",
                'if [ -n "$REWRITE_PATH" ]; then cp "$REWRITE_PATH" "$VULNERABILITY_PATH"; fi',
                "has_new_strix_vulnerability_report_artifact",
            )
        )
        rewrite_path = Path(temp) / "rewrite.md"
        if rewrite is not None:
            rewrite_path.write_bytes(rewrite)
            rewrite_argument = str(rewrite_path)
        else:
            rewrite_argument = ""
        completed = subprocess.run(
            [
                "bash",
                "-c",
                script,
                "strix-vulnerability-provenance",
                str(reports),
                str(vulnerability),
                rewrite_argument,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode not in {0, 1}:
        raise AssertionError(completed.stderr)
    return completed.returncode == 0


def _accepts_recovered_warning(extra_console: str) -> bool:
    """Run the current-attempt structured completion classifier verbatim."""

    source = STRIX_GATE.read_text(encoding="utf-8")
    function = _function_block(
        source,
        "strix_report_has_authoritative_recovered_transient_completion",
    )
    with tempfile.TemporaryDirectory(prefix="strix-current-attempt-") as temp:
        report = Path(temp) / "report"
        report.mkdir()
        (report / "run.json").write_text(
            '{"status":"completed","scan_results":'
            '{"scan_completed":true,"success":true}}\n',
            encoding="utf-8",
        )
        (report / "findings.sarif").write_text(
            '{"version":"2.1.0","runs":[{"results":[]}]}\n',
            encoding="utf-8",
        )
        (report / "strix.log").write_text(
            "2026-09-05 10:03:16.171 WARNING run - "
            "strix.core.execution: transient model/provider error for c0ffee12; "
            "replaying turn (attempt 1/5, backoff 2.0s): temporary HTTP 500\n",
            encoding="utf-8",
        )
        console = Path(temp) / "console.log"
        console.write_text(extra_console, encoding="utf-8")
        script = "\n".join(
            (
                "set -euo pipefail",
                "declare -A ATTEMPT_START_RUN_RECORD_DIGESTS=()",
                function,
                'strix_report_has_authoritative_recovered_transient_completion "$1" "$2"',
            )
        )
        completed = subprocess.run(
            ["bash", "-c", script, "strix-current-attempt", str(report), str(console)],
            check=False,
            capture_output=True,
            text=True,
        )
    if completed.returncode not in {0, 1}:
        raise AssertionError(completed.stderr)
    return completed.returncode == 0


class StrixAttemptEvidenceProvenanceTests(unittest.TestCase):
    """Protect fresh content evidence and fail-closed terminal signals."""

    def test_in_place_vulnerability_report_rewrite_is_new_evidence(self) -> None:
        """A current attempt may reuse a report path but replace its contents."""

        self.assertTrue(
            _vulnerability_artifact_is_new(
                rewrite=b"# Finding\n\nSeverity: INFO\nAttempt: second\n"
            )
        )

    def test_unchanged_vulnerability_report_is_not_new_evidence(self) -> None:
        """An untouched predecessor report must not validate a later attempt."""

        self.assertFalse(_vulnerability_artifact_is_new(rewrite=None))

    def test_github_error_command_overrides_recovered_warning_completion(self) -> None:
        """A typed console error remains terminal even beside clean receipts."""

        self.assertFalse(
            _accepts_recovered_warning(
                "scan completed after replay\n::error::artifact publication failed\n"
            )
        )

    def test_recovered_warning_with_clean_console_is_accepted(self) -> None:
        """The narrow Inkspan recovered-transient exception remains supported."""

        self.assertTrue(_accepts_recovered_warning("scan completed after replay\n"))


if __name__ == "__main__":
    unittest.main()
