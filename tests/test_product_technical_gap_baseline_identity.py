from pathlib import Path


BASELINE = Path(__file__).parents[1] / "docs" / "product-technical-gap-baseline.md"
OWNER_QUALIFIED_EVIDENCE = (
    "ContextualWisdomLab/contextual-orchestrator#1149@684cf28f",
    "ContextualWisdomLab/fast-mlsirm@09f762d",
)
OWNERLESS_EVIDENCE = (
    "contextual-orchestrator#1149@684cf28f",
    "fast-mlsirm@09f762d",
)


def test_cross_repository_evidence_keeps_owner_identity() -> None:
    """Cross-repository receipts must remain resolvable outside local repo context."""
    baseline = BASELINE.read_text(encoding="utf-8")

    for reference in OWNER_QUALIFIED_EVIDENCE:
        assert f"`{reference}`" in baseline
    for reference in OWNERLESS_EVIDENCE:
        assert f"`{reference}`" not in baseline
