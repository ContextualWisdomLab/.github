"""Guard complete instruction projections, not the quality of model judgments."""

from pathlib import Path
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SKILL_PATH = Path(".agents/skills/cwl-review-evidence/SKILL.md")
PROMPT_PATHS = (Path("ci-review-prompt.md"), Path("code-reviewer-prompt.md"))
START_MARKER = "<!-- cwl-review-evidence:start -->\n"
END_MARKER = "<!-- cwl-review-evidence:end -->"


def projection_body(document_text: str) -> str:
    """Reject absent, duplicate, empty or reversed projection boundaries."""
    if document_text.count(START_MARKER) != 1:
        raise ValueError("exactly one projection start is required")
    if document_text.count(END_MARKER) != 1:
        raise ValueError("exactly one projection end is required")
    start_offset = document_text.index(START_MARKER) + len(START_MARKER)
    end_offset = document_text.index(END_MARKER)
    if end_offset <= start_offset:
        raise ValueError("projection must be nonempty and ordered")
    return document_text[start_offset:end_offset]


class ReviewSkillProjectionTests(unittest.TestCase):
    """Check the packaged skill and both trusted prompt projections agree."""

    def test_ci_prompt_contains_the_complete_skill(self) -> None:
        """A missing or stale CI projection must fail before publication."""
        self.check_consumer_projection(PROMPT_PATHS[0])

    def test_standalone_prompt_contains_the_complete_skill(self) -> None:
        """The standalone reviewer must receive the same procedure revision."""
        self.check_consumer_projection(PROMPT_PATHS[1])

    def check_consumer_projection(self, prompt_path: Path) -> None:
        """Compare actual packaged consumer bytes with the canonical skill body."""
        skill_path = REPOSITORY_ROOT / SKILL_PATH
        self.assertTrue(skill_path.is_file(), "canonical review skill is absent")
        skill_text = skill_path.read_text(encoding="utf-8")
        prompt_text = (REPOSITORY_ROOT / prompt_path).read_text(encoding="utf-8")
        self.assertEqual(projection_body(prompt_text), projection_body(skill_text))

    def test_malformed_projection_boundaries_are_rejected(self) -> None:
        """Fail closed rather than accept a partial or ambiguous instruction set."""
        invalid_documents = (
            "",
            START_MARKER + "procedure\n",
            "procedure\n" + END_MARKER,
            START_MARKER + END_MARKER,
            END_MARKER + START_MARKER,
            START_MARKER + START_MARKER + "procedure\n" + END_MARKER,
            START_MARKER + "procedure\n" + END_MARKER + END_MARKER,
        )
        for document_text in invalid_documents:
            with self.subTest(document_text=document_text):
                with self.assertRaises(ValueError):
                    projection_body(document_text)


if __name__ == "__main__":
    unittest.main()
