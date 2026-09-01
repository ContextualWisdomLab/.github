from pathlib import Path


PROMPTS = (
    Path("ci-review-prompt.md"),
    Path("code-reviewer-prompt.md"),
)


def test_review_prompts_do_not_turn_identifier_shape_into_blocking_authority() -> None:
    """Lexical naming and identifier shape are seeds, never standalone defects."""
    for prompt_path in PROMPTS:
        prompt = prompt_path.read_text(encoding="utf-8")

        assert "two or more meaningful words" not in prompt
        assert "when exposure is unclear, treat it as exposed" not in prompt
        assert "Coupang breach" not in prompt
        assert "signal, not automatic proof of IDOR" in prompt
        assert "Never turn a lexical word-count rule into review authority" in prompt
        assert "actively try to falsify the seed before blocking" in prompt


def test_identifier_blockers_require_a_concrete_consumer_or_security_path() -> None:
    """A blocking naming/ID finding must identify an observable causal surface."""
    for prompt_path in PROMPTS:
        prompt = prompt_path.read_text(encoding="utf-8")

        assert "Trace the actual authorization and lookup path" in prompt
        assert "Public or properly authorized sequential identifiers" in prompt
        assert "specific consumer, parser, database, serializer, generator" in prompt
        assert "source-backed consequence" in prompt
