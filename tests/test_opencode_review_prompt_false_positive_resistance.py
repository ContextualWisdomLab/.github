from pathlib import Path

import pytest


PROMPTS = (
    Path("ci-review-prompt.md"),
    Path("code-reviewer-prompt.md"),
    Path("scripts/ci/opencode_review_prompt_template.md"),
)

ADVERSARIAL_PREFIXES = {
    Path("ci-review-prompt.md"): "Perform an explicit adversarial phase before every verdict.",
    Path("code-reviewer-prompt.md"): "Run a dedicated adversarial phase before the verdict.",
    Path("scripts/ci/opencode_review_prompt_template.md"): "Adversarial validation is mandatory before every verdict.",
}


def paragraph_starting(prompt: str, prefix: str) -> str:
    """Return one exact policy paragraph instead of accepting scattered substrings."""
    paragraphs = [part.strip() for part in prompt.split("\n\n") if part.strip()]
    matches = [paragraph for paragraph in paragraphs if paragraph.startswith(prefix)]
    assert len(matches) == 1, (prefix, matches)
    return " ".join(matches[0].split())


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_review_prompts_do_not_turn_identifier_shape_into_blocking_authority(
    prompt_path: Path,
) -> None:
    """Lexical naming and identifier shape are seeds, never standalone defects."""
    prompt = prompt_path.read_text(encoding="utf-8")
    identifier_policy = paragraph_starting(
        prompt,
        "Identifier exposure and enumeration deserve adversarial security review",
    )
    naming_policy = paragraph_starting(
        prompt,
        "For newly added or renamed identifiers",
    )
    adversarial_policy = paragraph_starting(
        prompt,
        ADVERSARIAL_PREFIXES[prompt_path],
    )

    assert "signal, not automatic proof of IDOR" in identifier_policy
    assert "Trace the actual authorization and lookup path" in identifier_policy
    assert "Public or properly authorized sequential identifiers can be acceptable" in identifier_policy
    assert "rather than assuming the identifier is exposed or exploitable" in identifier_policy
    assert "they do not substitute for authorization" in identifier_policy

    assert "Short or single-word names are acceptable when idiomatic and unambiguous" in naming_policy
    assert "Never turn a lexical word-count rule into review authority" in naming_policy
    assert "the specific consumer, parser, database, serializer, generator" in naming_policy
    assert "security boundary, or compatibility behavior it can break" in naming_policy

    assert "actively try to falsify the seed before blocking" in adversarial_policy
    assert "the seed itself is never evidence of a defect" in adversarial_policy

    for retired_rule in (
        "two or more meaningful words",
        "when exposure is unclear, treat it as exposed",
        "Coupang breach",
    ):
        assert retired_rule not in prompt


@pytest.mark.parametrize("prompt_path", PROMPTS, ids=lambda path: path.name)
def test_naming_blocker_paragraph_requires_source_backed_causal_surface(
    prompt_path: Path,
) -> None:
    """Blocking naming policy must bind the exact name to an observable consumer."""
    prompt = prompt_path.read_text(encoding="utf-8")
    naming_review = paragraph_starting(prompt, "Review object naming and reserved-word safety")

    assert "blocking finding only when the changed name has a source-backed consequence" in naming_review
    assert "real reserved-word collision" in naming_review
    assert "ambiguous serialization or generated code" in naming_review
    assert "incompatible public/API contract" in naming_review
    assert "Do not infer a defect from a name's word count" in naming_review
