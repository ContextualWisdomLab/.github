"""Regression contract for owner-qualified cross-repository evidence identities."""

from pathlib import Path
import re
import unittest


BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "product-technical-gap-baseline.md"
)
CHANGELOG_PATH = Path(__file__).resolve().parents[1] / "CHANGELOG.md"


class ProductTechnicalGapBaselineRepositoryIdentityContractTests(unittest.TestCase):
    """Keep durable cross-repository evidence unambiguous outside its owner repo."""

    def test_control_opencode_evidence_uses_owner_qualified_repository_identities(self) -> None:
        """Reject the two legacy bare repository tokens and require their durable forms."""
        baseline = BASELINE_PATH.read_text(encoding="utf-8")

        legacy_tokens = (
            "`contextual-orchestrator#1149@684cf28f`",
            "`fast-mlsirm@09f762d`",
        )
        durable_tokens = (
            "`ContextualWisdomLab/contextual-orchestrator#1149@684cf28f`",
            "`ContextualWisdomLab/fast-mlsirm@09f762d`",
        )

        for token in legacy_tokens:
            with self.subTest(token=token):
                self.assertNotIn(token, baseline)

        for token in durable_tokens:
            with self.subTest(token=token):
                self.assertIn(token, baseline)

    def test_orgmetra_evidence_uses_owner_qualified_issue_identity(self) -> None:
        """Keep the Job Analysis evidence linked to its owning repository."""
        baseline = BASELINE_PATH.read_text(encoding="utf-8")
        changelog = CHANGELOG_PATH.read_text(encoding="utf-8")

        self.assertNotIn("Orgmetra #63", changelog)
        self.assertNotIn("Orgmetra #63", baseline)
        self.assertIsNone(re.search(r"Orgmetra\s+#63 consumer run", baseline))
        self.assertIn("ContextualWisdomLab/orgmetra#63", changelog)
        self.assertGreaterEqual(
            baseline.count("ContextualWisdomLab/orgmetra#63"), 3
        )


if __name__ == "__main__":
    unittest.main()
