"""Contract tests for central required review workflow runner images."""

from __future__ import annotations

from pathlib import Path
import unittest


STRIX = Path(".github/workflows/strix.yml")
OPENCODE_REVIEW = Path(".github/workflows/opencode-review.yml")
NOEMA_REVIEW = Path(".github/workflows/noema-review.yml")


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


if __name__ == "__main__":
    unittest.main()
