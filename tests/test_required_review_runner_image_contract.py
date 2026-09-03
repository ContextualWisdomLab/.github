"""Contract tests for central required review workflow runner images."""

from __future__ import annotations

from pathlib import Path
import unittest


STRIX = Path(".github/workflows/strix.yml")
OPENCODE_REVIEW = Path(".github/workflows/opencode-review.yml")
NOEMA_REVIEW = Path(".github/workflows/noema-review.yml")


class RequiredReviewRunnerImageContract(unittest.TestCase):
    """Keep required review jobs off the observed starved floating image."""

    def test_strix_uses_explicit_supported_image(self) -> None:
        """Require every Strix job to use explicit Ubuntu 24.04.

        4, not 3: the `changed-scope` gate job added to skip doc/image-only
        PRs (org ruleset 18156473 ignores trigger-level path filters) is a
        fourth job on this image.
        """
        workflow = STRIX.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 4)

    def test_opencode_review_uses_explicit_supported_image(self) -> None:
        """Require every OpenCode Review job to use explicit Ubuntu 24.04."""
        workflow = OPENCODE_REVIEW.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 5)

    def test_noema_review_uses_explicit_supported_image(self) -> None:
        """Require every Noema Review job to use explicit Ubuntu 24.04.

        3, not 2: docs/doctoring/item13-stale-head-cancellation-audit-20260903.md's
        fix split the live-head-validated cancellation logic out of the
        noema-review job into its own structurally separate
        cancel-superseded-noema-runs job (mirroring strix.yml's
        cancel-superseded-pr-runs and opencode-review.yml's
        cancel-superseded-opencode-review-runs), a third job on this image.
        """
        workflow = NOEMA_REVIEW.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 3)


if __name__ == "__main__":
    unittest.main()
