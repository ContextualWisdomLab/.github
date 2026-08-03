"""Contract tests for the buyer-facing organization product catalog."""

from pathlib import Path


PROFILE = Path("profile/README.md")


def test_profile_uses_current_product_names_and_repositories() -> None:
    """Keep the public catalog aligned with active product identities."""
    profile = PROFILE.read_text(encoding="utf-8")

    assert "VibeSec" not in profile
    assert "ContextualWisdomLab/appguardrail" in profile
    assert "ContextualWisdomLab/RankWeave" in profile
    assert "ContextualWisdomLab/fast-mlsirm" in profile


def test_profile_states_standalone_and_module_integration_contract() -> None:
    """Expose the portfolio's standalone-product and reusable-module posture."""
    profile = PROFILE.read_text(encoding="utf-8")

    assert "useful on its own" in profile
    assert "stable module boundaries" in profile
    assert "integration into larger Contextual Wisdom Lab systems" in profile
