"""Coverage contract for ConceptWeave's canonical bounded review-repair target."""

from __future__ import annotations

import json
import re
from pathlib import Path


_CALLER = Path(".github/workflows/hourly-review-repair.yml")
_DISPATCH_TARGETS_MIRROR = Path("scripts/ci/opencode_repository_dispatch_targets.json")
_TARGET = "ContextualWisdomLab/ConceptWeave"


def test_conceptweave_has_exactly_one_canonical_review_repair_target() -> None:
    """ConceptWeave resolves once through the central caller and dispatch allowlist mirror."""
    caller = _CALLER.read_text(encoding="utf-8")
    matches = re.findall(
        r'\{"name":"conceptweave","target_repository":"ContextualWisdomLab/ConceptWeave",'
        r'"base_branch":"main","retry_hours":"2",'
        r'"concurrency_group":"conceptweave-hourly-review-repair"\}',
        caller,
    )
    assert len(matches) == 1

    mirror = json.loads(_DISPATCH_TARGETS_MIRROR.read_text(encoding="utf-8"))
    assert mirror["targets"].count(_TARGET) == 1


def test_conceptweave_target_uses_shared_caller_without_a_duplicate_workflow() -> None:
    """Enrollment stays in the consolidated central caller rather than a new thin workflow."""
    assert not Path(".github/workflows/conceptweave-hourly-review-repair.yml").exists()
