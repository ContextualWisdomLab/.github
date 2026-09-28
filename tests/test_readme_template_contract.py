"""Guard the authoring scaffold without claiming to validate product truth."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
STANDARD_PATH = REPOSITORY_ROOT / "docs/repository-readme-quality-standard.md"
TEMPLATE_PATH = REPOSITORY_ROOT / "docs/templates/repository-readme-template.md"


class ReadmeTemplateContractTests(unittest.TestCase):
    """Check discoverability, safe placeholders, and honest integration status."""

    def test_standard_links_to_the_adaptable_template(self):
        """A checklist alone must not stand in for the requested writing scaffold."""
        standard_text = STANDARD_PATH.read_text(encoding="utf-8")
        self.assertIn("(templates/repository-readme-template.md)", standard_text)
        self.assertNotIn("quality contract, not a copy-and-paste template", standard_text)

    def test_template_contains_one_non_executable_product_scaffold(self):
        """The scaffold has reader sections, but no invented commands or badges."""
        self.assertTrue(TEMPLATE_PATH.is_file(), "The reusable README template is missing")
        template_text = TEMPLATE_PATH.read_text(encoding="utf-8")
        self.assertEqual(template_text.count("<!-- readme-template:start -->"), 1)
        self.assertEqual(template_text.count("<!-- readme-template:end -->"), 1)
        scaffold_text = template_text.split("<!-- readme-template:start -->", 1)[1].split(
            "<!-- readme-template:end -->", 1
        )[0]
        for heading_text in (
            "# {{product_name}}", "## What you can do", "## Get started",
            "## Example", "## How it fits", "## Status and verification",
            "## Documentation", "## Support and contributing", "## License",
        ):
            with self.subTest(heading=heading_text):
                self.assertIn(heading_text, scaffold_text)
        self.assertIn("{{verified_license_statement}}", scaffold_text)
        self.assertIn("{{observed_result_and_next_action}}", scaffold_text)
        self.assertNotIn("```bash", scaffold_text)
        self.assertNotIn("https://", scaffold_text)
        self.assertNotIn("![", scaffold_text)

    def test_standard_requires_execution_and_side_effect_evidence(self):
        """A command's presence in a file is not evidence that onboarding worked."""
        standard_text = STANDARD_PATH.read_text(encoding="utf-8")
        for evidence_label in (
            "Working directory", "Runtime and lock", "Observed result",
            "Side effects", "Stop and recovery", "Not executed",
        ):
            with self.subTest(evidence=evidence_label):
                self.assertIn(evidence_label, standard_text)

    def test_external_blocker_is_not_completion(self):
        """Blocked work retains ownership instead of being marked finished."""
        standard_text = STANDARD_PATH.read_text(encoding="utf-8")
        self.assertIn("A blocker leaves the work incomplete", standard_text)
        self.assertNotIn("integrated or a real external blocker remains", standard_text)
        self.assertIn("every valid delta", standard_text)


if __name__ == "__main__":
    unittest.main()
