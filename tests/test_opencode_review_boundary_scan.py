"""Regression contracts for bounded runtime-evidence sentence scans."""

import pytest

from scripts.ci import opencode_review_normalize_output as normalizer


@pytest.mark.parametrize("sentence_boundary", [".", ";", "\\n"])
def test_runtime_tool_claim_uses_the_nearest_sentence_boundary(sentence_boundary):
    """A neighbouring sentence cannot transfer execution or negation evidence."""
    assert normalizer.claimed_runtime_tools(
        f"Chrome was not executed{sentence_boundary} Playwright verified the route."
    ) == ("playwright",)
    assert normalizer.claimed_runtime_tools(
        f"Chrome verified the route{sentence_boundary} Playwright was not executed."
    ) == ("chrome",)
