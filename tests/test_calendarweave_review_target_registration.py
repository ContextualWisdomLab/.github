"""Keep CalendarWeave admitted to the central exact-head review target mirror."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "ContextualWisdomLab/CalendarWeave"


def test_calendarweave_review_target_is_explicit_and_unique() -> None:
    """Register the public calendar repository once without broad wildcard admission."""
    mirror = ROOT / "scripts/ci/opencode_repository_dispatch_targets.json"
    targets = json.loads(mirror.read_text(encoding="utf-8"))["targets"]
    assert targets.count(TARGET) == 1
    assert len(targets) == len(set(targets))
