"""Traceability contracts for cross-repository evidence in the product/technical baseline."""

import re
from pathlib import Path

BASELINE_PATH = Path(__file__).resolve().parents[1] / "docs" / "product-technical-gap-baseline.md"


def test_cross_repository_evidence_uses_fully_qualified_owner_identity() -> None:
    """Cross-repository exact-head evidence must retain owner/repository identity."""
    source = BASELINE_PATH.read_text(encoding="utf-8")

    assert "ContextualWisdomLab/contextual-orchestrator#1149@684cf28f" in source
    assert "ContextualWisdomLab/fast-mlsirm@09f762d" in source
    assert re.search(r"(?<!ContextualWisdomLab/)contextual-orchestrator#1149@684cf28f", source) is None
    assert re.search(r"(?<!ContextualWisdomLab/)fast-mlsirm@09f762d", source) is None
