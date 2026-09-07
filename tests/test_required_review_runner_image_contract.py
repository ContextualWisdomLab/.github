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
        """Require every OpenCode Review job to use explicit Ubuntu 24.04."""
        self.assert_explicit_supported_image(OPENCODE_REVIEW)

    def test_noema_review_uses_explicit_supported_image(self) -> None:
        """Require every Noema Review job to use explicit Ubuntu 24.04."""
        self.assert_explicit_supported_image(NOEMA_REVIEW)

    def test_opencode_review_dispatch_uses_explicit_supported_image(self) -> None:
        """Require every OpenCode Review Dispatch job to use explicit Ubuntu 24.04.

        This is the workflow the required `opencode-review` check's
        `repository_dispatch` actually lands on to run the OpenCode CLI and
        post the exact-head verdict; a starved floating image here queues
        the real review work for hours just as surely as on the required
        check itself (see docs/product-technical-gap-baseline.md's
        2026-09-01 entry, whose own "Residual" note flagged this exact
        follow-up sweep as still open).
        """
        self.assert_explicit_supported_image(OPENCODE_REVIEW_DISPATCH)


if __name__ == "__main__":
    unittest.main()
