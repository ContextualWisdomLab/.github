"""Regression contract for Strix's own local-proxy bootstrap failures.

Strix bootstraps a local interception proxy (Caido) before it can run a scan.
When that bootstrap itself fails -- for example the runner's local port is
refused -- the gate script classifies it as a non-retryable infrastructure
failure and logs "Strix scan failed after provider infrastructure or
failure-signal output; failing closed." (scripts/ci/strix_quick_gate.sh's
`run_current_target_scan`, no fallback attempted because
`is_model_retryable_error` doesn't recognize a local proxy-login failure as
an LLM-provider error). Before this fix, the workflow's neutral-skip regex
only matched the "emitted ..." wording variant of that message family, so
this specific "scan failed after ..." wording fell through to a hard
required-check failure even though zero vulnerabilities were reported.

Observed live in ContextualWisdomLab/LineageWeave PR #392 (job
97019252804): `loginAsGuest failed after 10 attempts: curl exit 7: ...
Failed to connect to 127.0.0.1 port 48080`, "Vulnerabilities 0", then
"Strix scan failed after provider infrastructure or failure-signal output;
failing closed." -- a pure CI-infrastructure hiccup that still failed the
required check.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STRIX_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "strix.yml"

# The exact shape observed in PR #392's failing run: a local Caido/proxy
# bootstrap failure after the model itself reported zero vulnerabilities.
LOCAL_PROXY_BOOTSTRAP_FAILURE = (
    "Model nvidia_nim/nvidia/nemotron-3-super-120b-a12b\n"
    "Vulnerabilities 0\n"
    "Error during penetration test: loginAsGuest failed after 10 attempts: "
    "curl exit 7: curl: (7) Failed to connect to 127.0.0.1 port 48080 after "
    "0 ms: Could not connect to server\n"
    "Strix run failed for model 'nvidia_nim/nvidia/nemotron-3-super-120b-a12b' "
    "after 163s (exit code 1).\n"
    "Strix scan failed after provider infrastructure or failure-signal "
    "output; failing closed.\n"
)


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
    with tempfile.TemporaryDirectory(prefix="strix-local-proxy-") as temp_dir:
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


class StrixLocalProxyBootstrapFailureTests(unittest.TestCase):
    """Protect the PR #392-shaped local-proxy failure without weakening the gate."""

    def test_workflow_recognizes_the_scan_failed_after_wording_variant(self) -> None:
        workflow = STRIX_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("provider infrastructure or failure-signal output", workflow)
        # The narrower "emitted ..." wording must not have silently regressed
        # back in as the only recognized variant.
        self.assertNotIn(
            "emitted provider infrastructure or failure-signal output",
            workflow,
        )

    def test_neutralizes_local_proxy_bootstrap_failure_with_zero_findings(self) -> None:
        self.assertTrue(_workflow_neutralizes(LOCAL_PROXY_BOOTSTRAP_FAILURE))

    def test_still_fails_closed_when_a_real_vulnerability_is_also_reported(
        self,
    ) -> None:
        log = LOCAL_PROXY_BOOTSTRAP_FAILURE + (
            "Vulnerability Report\nSeverity: CRITICAL\nVulnerabilities 1\n"
        )
        self.assertFalse(_workflow_neutralizes(log))


if __name__ == "__main__":
    unittest.main()
