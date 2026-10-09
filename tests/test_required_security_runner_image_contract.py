"""Contract tests for central required security workflow runner images."""

from __future__ import annotations

from pathlib import Path
import unittest


SECURITY_SCAN = Path(".github/workflows/security-scan.yml")
SAST_SEMGREP = Path(".github/workflows/sast-semgrep.yml")


class RequiredSecurityRunnerImageContract(unittest.TestCase):
    """Keep security jobs on isolated runners where required, with a fixed fallback."""

    def assert_runner_routing_contract(
        self,
        workflow: str,
        *,
        workflow_name: str,
        expected_jobs: int,
    ) -> None:
        """Require trusted-main, isolated-product, and hosted-fallback routes."""
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        runner_lines = [
            line.strip()
            for line in workflow.splitlines()
            if line.strip().startswith("runs-on:")
        ]
        self.assertEqual(len(runner_lines), expected_jobs)
        required_fragments = (
            "github.repository == 'ContextualWisdomLab/.github'",
            "github.repository == 'ContextualWisdomLab/fast-mlsirm'",
            "github.workflow_ref == "
            f"'ContextualWisdomLab/.github/.github/workflows/{workflow_name}"
            "@refs/heads/main'",
            '"group":"CWL MCP remediation"',
            '"group":"CWL CI isolated"',
            "fromJSON('[\"ubuntu-24.04\"]')",
        )
        for runner_line in runner_lines:
            for fragment in required_fragments:
                self.assertIn(fragment, runner_line)

    def test_security_scan_uses_explicit_supported_image(self) -> None:
        """Require each Security Scan job to preserve all three runner routes.

        Six jobs route fast-mlsirm PR work to the isolated group, central-main
        work to the remediation group, and every other consumer to Ubuntu 24.04.
        """
        workflow = SECURITY_SCAN.read_text(encoding="utf-8")
        self.assert_runner_routing_contract(
            workflow,
            workflow_name="security-scan.yml",
            expected_jobs=6,
        )

    def test_sast_semgrep_uses_explicit_supported_image(self) -> None:
        """Require the SAST Semgrep job to preserve all three runner routes.

        `#1656` removed the sibling `cancel-closed-pr-runs` no-op job (it
        only duplicated PR-stable workflow concurrency), leaving one runner
        job in this workflow instead of two. It was 2, not 1, again after the
        `changed-scope` gate job was added to skip doc-only PR scope (org
        ruleset 18156473 ignores trigger-level path filters). The count
        returned to 1 when that `changed-scope` job was folded into the
        `semgrep` job as a step-level guard (one consumer, one runner).
        """
        workflow = SAST_SEMGREP.read_text(encoding="utf-8")
        self.assert_runner_routing_contract(
            workflow,
            workflow_name="sast-semgrep.yml",
            expected_jobs=1,
        )


if __name__ == "__main__":
    unittest.main()
