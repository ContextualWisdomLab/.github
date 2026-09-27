"""Contract tests for central required review workflow runner images."""

from __future__ import annotations

from pathlib import Path
import unittest


STRIX = Path(".github/workflows/strix.yml")
OPENCODE_REVIEW = Path(".github/workflows/opencode-review.yml")
NOEMA_REVIEW = Path(".github/workflows/noema-review.yml")
OPENCODE_REVIEW_DISPATCH = Path(".github/workflows/opencode-review-dispatch.yml")


class RequiredReviewRunnerImageContract(unittest.TestCase):
    """Keep required review jobs off the observed starved floating image."""

    def assert_explicit_supported_image(self, path: Path) -> None:
        """Require every job runner declaration to pin Ubuntu 24.04."""
        runs_on = {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("runs-on:")
        }
        self.assertTrue(runs_on)
        self.assertEqual(runs_on, {"runs-on: ubuntu-24.04"})

    def test_strix_uses_explicit_supported_image(self) -> None:
        """Require every Strix job to use explicit Ubuntu 24.04."""
        self.assert_explicit_supported_image(STRIX)

    def test_opencode_review_uses_explicit_supported_image(self) -> None:
        """Keep metadata-only OpenCode admission on the trusted control pool."""
        workflow = OPENCODE_REVIEW.read_text(encoding="utf-8")
        self.assertEqual(workflow.count('"group":"CWL central control"'), 6)
        self.assertEqual(workflow.count('"labels":["self-hosted","linux","x64"]'), 6)
        self.assertNotIn("runs-on: ubuntu-24.04", workflow)
        self.assertNotIn("actions/checkout", workflow)
        self.assertEqual(workflow.count("github.workflow_ref == 'ContextualWisdomLab/.github/.github/workflows/opencode-review.yml@refs/heads/main'"), 6)
        self.assertEqual(workflow.count("fromJSON('[\"ubuntu-24.04\"]')"), 6)

    def test_noema_review_uses_explicit_supported_image(self) -> None:
        """Require every Noema Review job to use explicit Ubuntu 24.04."""
        workflow = NOEMA_REVIEW.read_text(encoding="utf-8")
        self.assertEqual(workflow.count("endsWith(github.workflow_ref, '@refs/heads/main')"), 5)
        self.assertEqual(workflow.count('"group":"CWL MCP remediation"'), 5)
        self.assertEqual(workflow.count('"labels":["self-hosted","linux","x64"]'), 5)
        self.assertEqual(workflow.count("github.repository == 'ContextualWisdomLab/contextual-orchestrator'"), 5)
        self.assertEqual(workflow.count("fromJSON('[\"ubuntu-24.04\"]')"), 5)
        self.assertNotIn("runs-on: ubuntu-24.04", workflow)

    def test_opencode_review_dispatch_uses_explicit_supported_image(self) -> None:
        """Require OpenCode dispatch jobs to use the compatible dedicated group.

        This is the workflow the required `opencode-review` check's
        `repository_dispatch` actually lands on to run the OpenCode CLI and
        post the exact-head verdict; a starved floating image here queues
        the real review work for hours just as surely as on the required
        check itself (see docs/product-technical-gap-baseline.md's
        2026-09-01 entry, whose own "Residual" note flagged this exact
        follow-up sweep as still open).
        """
        workflow = OPENCODE_REVIEW_DISPATCH.read_text(encoding="utf-8")
        self.assertEqual(workflow.count("group: CWL central OpenCode"), 3)
        self.assertEqual(workflow.count("labels: [self-hosted, linux, x64]"), 3)
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertNotIn("runs-on: ubuntu-24.04", workflow)


if __name__ == "__main__":
    unittest.main()


def test_codeql_pr_routes_only_explicit_repositories_to_existing_trusted_group() -> None:
    """Central and gateway callers reuse workers; every other caller keeps hosted access."""
    workflow = Path(".github/workflows/codeql-pr.yml").read_text()
    assert workflow.count("endsWith(github.workflow_ref, '@refs/heads/main')") == 3
    assert workflow.count('"group":"CWL MCP remediation"') == 3
    assert workflow.count("github.repository == 'ContextualWisdomLab/.github'") == 3
    assert workflow.count("github.repository == 'ContextualWisdomLab/contextual-orchestrator'") == 3
    assert workflow.count("fromJSON('[\"ubuntu-24.04\"]')") == 3
