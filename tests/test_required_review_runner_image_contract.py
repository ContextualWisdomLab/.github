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
        """Require every Strix job to use explicit Ubuntu 24.04."""
        workflow = STRIX.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 3)

    def test_opencode_review_uses_explicit_supported_image(self) -> None:
        """Require every OpenCode Review job to use explicit Ubuntu 24.04."""
        workflow = OPENCODE_REVIEW.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 5)

    def test_noema_review_uses_explicit_supported_image(self) -> None:
        """Require every Noema Review job to use explicit Ubuntu 24.04."""
        workflow = NOEMA_REVIEW.read_text(encoding="utf-8")
        self.assertNotIn("runs-on: ubuntu-latest", workflow)
        self.assertEqual(workflow.count("runs-on: ubuntu-24.04"), 2)


if __name__ == "__main__":
    unittest.main()
