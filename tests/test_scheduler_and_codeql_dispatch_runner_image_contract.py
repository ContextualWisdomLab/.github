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

import unittest
from pathlib import Path

PR_REVIEW_AUTOFIX = Path(".github/workflows/pr-review-autofix.yml")
PR_REVIEW_FIX_SCHEDULER = Path(".github/workflows/pr-review-fix-scheduler.yml")
HOURLY_REVIEW_REPAIR = Path(".github/workflows/hourly-review-repair.yml")
CODEQL_PR = Path(".github/workflows/codeql-pr.yml")
CODEQL_SCAN_DISPATCH = Path(".github/workflows/codeql-scan-dispatch.yml")
PYTHON_SECURITY = Path(".github/workflows/python-security.yml")


class SchedulerAndCodeqlDispatchRunnerImageContract(unittest.TestCase):
    """Keep these central callers/dispatchers off the observed starved image."""

    def assert_explicit_supported_image(self, path: Path) -> None:
        """Require every ordinary job to use isolated self-hosted Linux runners."""
        workflow = path.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow, path)
        self.assertIn("runs-on: [self-hosted, linux, x64, cwlab-ci-isolated]", workflow, path)

    def test_pr_review_autofix_uses_explicit_supported_image(self) -> None:
        """Require the PR Review Autofix job to use isolated self-hosted Linux."""
        self.assert_explicit_supported_image(PR_REVIEW_AUTOFIX)

    def test_pr_review_fix_scheduler_uses_explicit_supported_image(self) -> None:
        """Require the fix-scheduler's fallback to use isolated self-hosted Linux."""
        workflow = PR_REVIEW_FIX_SCHEDULER.read_text(encoding="utf-8")
        self.assertNotIn("ubuntu-latest", workflow)
        self.assertIn("fromJSON('[\"self-hosted\",\"linux\",\"x64\",\"cwlab-ci-isolated\"]')", workflow)

    def test_hourly_review_repair_uses_explicit_supported_image(self) -> None:
        """Require hourly control jobs to use the dedicated central group."""
        workflow = HOURLY_REVIEW_REPAIR.read_text(encoding="utf-8")
        self.assertIn("group: CWL central control", workflow)
        self.assertIn("labels: [self-hosted, linux, x64]", workflow)

    def test_codeql_pr_uses_explicit_supported_image(self) -> None:
        """Require trusted-main control routing and isolated fallback for all three jobs."""
        workflow = CODEQL_PR.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        selectors = [
            line.strip() for line in workflow.splitlines()
            if line.strip().startswith("runs-on:")
        ]
        self.assertEqual(len(selectors), 3)
        for selector in selectors:
            self.assertIn(
                "github.workflow_ref == 'ContextualWisdomLab/.github/.github/workflows/codeql-pr.yml@refs/heads/main'",
                selector,
            )
            self.assertIn('"group":"CWL central control"', selector)
            self.assertIn('"labels":["self-hosted","linux","x64"]', selector)
            self.assertIn("|| '[\"self-hosted\",\"linux\",\"x64\",\"cwlab-ci-isolated\"]'", selector)

    def test_codeql_scan_dispatch_uses_explicit_supported_image(self) -> None:
        """Require validation, scan, and attempt wake jobs in the dedicated group."""
        workflow = CODEQL_SCAN_DISPATCH.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("group: CWL central CodeQL"), 3)
        self.assertEqual(workflow.count("labels: [self-hosted, linux, x64]"), 3)

    def test_python_security_uses_explicit_supported_image(self) -> None:
        """Require all three Python Security jobs to select isolated self-hosted Linux."""
        workflow = PYTHON_SECURITY.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: [self-hosted, linux, x64, cwlab-ci-isolated]"), 3)


if __name__ == "__main__":
    unittest.main()
