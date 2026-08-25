"""Regression contract for typed backend failure after an exempted finding.

The Strix required check's console log can legitimately contain an
already-exempted vulnerability (out-of-scope unchanged-file evidence, or one
below the configured minimum severity) *and* a later, unrelated provider
outage in the same run: the gate first prints "... allowing pipeline
continuation." for the exempted finding, then a later fallback-model attempt
fails for an infrastructure reason (for example GitHub Models' scheduled
retirement brownout, HTTP 410 code `github_models_retirement_brownout`).

Before this fix, the workflow's outer neutral-skip decision grepped the whole
combined log for `reported_vulnerability_signal`, so the earlier -- already
exempted -- finding's own "Vulnerabilities N" / "severity:" text permanently
disqualified precise provider-failure classification. The fix scopes that
decision to the log tail after the last "allowing pipeline continuation"
marker while preserving a non-passing result for the incomplete scan. This
test extracts the actual bash block from the workflow (not a reimplementation)
and executes it against synthetic logs shaped like the real PR #392 run.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "strix.yml"

# An exempted finding: Strix reported a real vulnerability, but the gate
# itself already decided it is out of scope (unchanged files) and continued.
EXEMPTED_FINDING_AND_CONTINUATION = (
    "Vulnerability Report\n"
    "Severity: CRITICAL\n"
    "Vulnerabilities 1\n"
    "CRITICAL: 1\n"
    "Strix findings are limited to unchanged files in this pull request; "
    "allowing pipeline continuation.\n"
)

# The exact GitHub Models scheduled-retirement brownout observed in PR #392's
# required Strix check (run 32530198775, job 96920534139).
GITHUB_MODELS_BROWNOUT = (
    "LLM CONNECTION FAILED\n"
    "Could not establish connection to the language model.\n"
    "Error: Error code: 410 - {'error': {'code': "
    "'github_models_retirement_brownout', 'message': 'GitHub Models is "
    "temporarily unavailable as part of a scheduled retirement brownout.'}}\n"
    "Strix run failed for model 'github_models/openai/o3' after 5s "
    "(exit code 1).\n"
    "Configured model and fallback models were unavailable.\n"
)


def _extract_neutralization_block(workflow: str) -> str:
    """Return the gate's neutral-skip decision block, verbatim from the yml.

    Bounded by two unique anchors already present in the workflow so a future
    unrelated edit to this step fails the test instead of silently testing
    stale logic.
    """

    start_marker = (
        "          # Recognized signals that the LLM backend was unavailable"
    )
    terminal_failure_marker = (
        '          echo "Strix reported security findings or failed for a '
        'non-backend reason; failing the required check'
    )
    end_marker = '          exit "$strix_rc"\n'
    start = workflow.index(start_marker)
    terminal_failure = workflow.index(terminal_failure_marker, start)
    end = workflow.index(end_marker, terminal_failure) + len(end_marker)
    return workflow[start:end]


def _run_gate_tail(log_text: str) -> int:
    """Execute the extracted block against a synthetic log; return its exit code.

    A non-zero code is required because provider failure produced no
    authoritative complete vulnerability result.
    """

    workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
    block = _extract_neutralization_block(workflow)
    with tempfile.TemporaryDirectory(prefix="strix-tail-scope-") as temp_dir:
        strix_run_log = Path(temp_dir) / "strix_gate_console.log"
        strix_run_log.write_text(log_text, encoding="utf-8")
        script = "\n".join(
            (
                "set -uo pipefail",
                'strix_run_log="$1"',
                "strix_rc=1",
                block,
            )
        )
        completed = subprocess.run(
            [
                "bash",
                "-c",
                script,
                "strix-tail-scope",
                str(strix_run_log),
            ],
            check=False,
            capture_output=True,
            text=True,
            env={"RUNNER_TEMP": temp_dir, "PATH": "/usr/bin:/bin"},
        )
    return completed.returncode


class StrixBackendUnavailableAfterExemptedFindingTests(unittest.TestCase):
    """Protect the PR #392-shaped scenario without weakening the real gate."""

    def test_workflow_defines_the_tail_scoping_step(self) -> None:
        """Keep the fix's shape present so a future edit cannot drop it silently."""

        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("strix_neutralization_scope_log", workflow)
        self.assertIn("allowing pipeline continuation", workflow)
        self.assertIn("::error title=STRIX_PROVIDER_UNAVAILABLE::", workflow)
        self.assertNotIn("Treating as a neutral skip", workflow)

    def test_brownout_after_an_already_exempted_finding_is_non_passing(self) -> None:
        """The PR #392 shape remains typed and non-passing after an exemption."""

        log = EXEMPTED_FINDING_AND_CONTINUATION + GITHUB_MODELS_BROWNOUT
        self.assertEqual(_run_gate_tail(log), 1)

    def test_still_fails_closed_on_a_finding_reported_after_continuation(self) -> None:
        """A real finding surfacing *after* the continuation marker still blocks."""

        log = (
            EXEMPTED_FINDING_AND_CONTINUATION
            + "Vulnerability Report\nSeverity: CRITICAL\nVulnerabilities 1\n"
        )
        self.assertEqual(_run_gate_tail(log), 1)

    def test_still_fails_closed_with_no_continuation_marker_at_all(self) -> None:
        """Preserve prior behavior: a bare unresolved finding still blocks."""

        log = "Vulnerability Report\nSeverity: CRITICAL\nVulnerabilities 1\n"
        self.assertEqual(_run_gate_tail(log), 1)

    def test_bare_backend_outage_with_no_finding_is_non_passing(
        self,
    ) -> None:
        """A pure outage still lacks authoritative scan evidence."""

        self.assertEqual(_run_gate_tail(GITHUB_MODELS_BROWNOUT), 1)


if __name__ == "__main__":
    unittest.main()
