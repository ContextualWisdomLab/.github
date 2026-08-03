"""Contract tests for the buyer-facing organization product catalog."""

from pathlib import Path


PROFILE = Path(__file__).resolve().parents[1] / "profile" / "README.md"


def public_projects_section(profile: str) -> str:
    """Return the bounded public-projects section from the organization profile."""
    return profile.split("## Public Projects", 1)[1].split("## Forked Projects", 1)[0]


def test_profile_uses_current_product_names_and_repositories() -> None:
    """Keep the public catalog aligned with active product identities."""
    profile = PROFILE.read_text(encoding="utf-8")
    public_projects = public_projects_section(profile)

    assert "VibeSec" not in public_projects
    assert (
        "- **[appguardrail](https://github.com/ContextualWisdomLab/appguardrail)**"
        in public_projects
    )
    assert (
        "- **[RankWeave](https://github.com/ContextualWisdomLab/RankWeave)**"
        in public_projects
    )
    assert (
        "- **[fast-mlsirm](https://github.com/ContextualWisdomLab/fast-mlsirm)**"
        in public_projects
    )


def test_profile_states_standalone_and_module_integration_contract() -> None:
    """Expose the portfolio's standalone-product and reusable-module posture."""
    profile = PROFILE.read_text(encoding="utf-8")
    public_projects = public_projects_section(profile)

    assert "useful on its own" in public_projects
    assert "stable module boundaries" in public_projects
    assert "integration into larger Contextual Wisdom Lab systems" in public_projects
