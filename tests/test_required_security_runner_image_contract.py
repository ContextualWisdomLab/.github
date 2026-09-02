"""Contract tests for central required security workflow runner images."""

from __future__ import annotations

from pathlib import Path
import unittest


SECURITY_SCAN = Path(".github/workflows/security-scan.yml")
SAST_SEMGREP = Path(".github/workflows/sast-semgrep.yml")


class RequiredSecurityRunnerImageContract(unittest.TestCase):
    """Keep required security jobs off the observed starved floating image."""

    def test_security_scan_uses_explicit_supported_image(self) -> None:
        """Require every Security Scan job to use explicit Ubuntu 24.04."""
        workflow = SECURITY_SCAN.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 4)

    def test_sast_semgrep_uses_explicit_supported_image(self) -> None:
        """Require the SAST Semgrep job to use explicit Ubuntu 24.04.

        `#1656` removed the sibling `cancel-closed-pr-runs` no-op job (it
        only duplicated PR-stable workflow concurrency), leaving one runner
        job in this workflow instead of two.
        """
        workflow = SAST_SEMGREP.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 1)


if __name__ == "__main__":
    unittest.main()
