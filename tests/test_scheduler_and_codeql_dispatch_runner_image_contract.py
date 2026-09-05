"""Contract tests for the remaining central caller/dispatch runner images.

`docs/product-technical-gap-baseline.md`'s starved-`ubuntu-latest` entry
deliberately scoped its fix to the one file with direct, confirmed live
evidence at the time, naming `pr-review-autofix.yml`,
`pr-review-fix-scheduler.yml`, `hourly-review-repair.yml`, `codeql-pr.yml`,
and `codeql-scan-dispatch.yml` as residual occurrences to revisit "if queuing
symptoms recur on them specifically." They did: all five, plus
`python-security.yml` (found independently while investigating the same
symptom), were still requesting the unpinned image.
"""

from __future__ import annotations

from pathlib import Path
import unittest


PR_REVIEW_AUTOFIX = Path(".github/workflows/pr-review-autofix.yml")
PR_REVIEW_FIX_SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")
HOURLY_REVIEW_REPAIR = Path(".github/workflows/hourly-review-repair.yml")
CODEQL_PR = Path(".github/workflows/codeql-pr.yml")
CODEQL_SCAN_DISPATCH = Path(".github/workflows/codeql-scan-dispatch.yml")
PYTHON_SECURITY = Path(".github/workflows/python-security.yml")


class SchedulerAndCodeqlDispatchRunnerImageContract(unittest.TestCase):
    """Keep these central callers/dispatchers off the observed starved image."""

    def assert_explicit_supported_image(self, path: Path) -> None:
        """Require every job runner declaration to pin Ubuntu 24.04."""
        workflow = path.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow, path)
        self.assertIn("runs-on: ubuntu-24.04", workflow, path)

    def test_pr_review_autofix_uses_explicit_supported_image(self) -> None:
        """Require the PR Review Autofix job to use explicit Ubuntu 24.04."""
        self.assert_explicit_supported_image(PR_REVIEW_AUTOFIX)

    def test_pr_review_fix_scheduler_uses_explicit_supported_image(self) -> None:
        """Require the reusable fix-scheduler dispatch job to pin Ubuntu 24.04."""
        self.assert_explicit_supported_image(PR_REVIEW_FIX_SCHEDULER)

    def test_hourly_review_repair_uses_explicit_supported_image(self) -> None:
        """Require the hourly review-repair resolve-target job to pin Ubuntu 24.04."""
        self.assert_explicit_supported_image(HOURLY_REVIEW_REPAIR)

    def test_codeql_pr_uses_explicit_supported_image(self) -> None:
        """Require both CodeQL PR compatibility-analysis jobs to pin Ubuntu 24.04."""
        workflow = CODEQL_PR.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 2)

    def test_codeql_scan_dispatch_uses_explicit_supported_image(self) -> None:
        """Require both CodeQL Scan Dispatch jobs to pin Ubuntu 24.04."""
        workflow = CODEQL_SCAN_DISPATCH.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 2)

    def test_python_security_uses_explicit_supported_image(self) -> None:
        """Require all three Python Security jobs to pin Ubuntu 24.04."""
        workflow = PYTHON_SECURITY.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 3)


if __name__ == "__main__":
    unittest.main()
