"""Regression contract for owner-qualified cross-repository evidence identities."""

from pathlib import Path
import unittest


BASELINE_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "product-technical-gap-baseline.md"
)


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


if __name__ == "__main__":
    unittest.main()
