"""Procurement 등록은 private 정책·App 실행 승인을 대신하지 않는다."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "ContextualWisdomLab/procurement-workbench"


def test_procurement_review_target_is_explicit_and_unique() -> None:
    """기존 중앙 source mirror에 제품을 정확히 한 번 등록한다."""
    mirror = ROOT / "scripts/ci/opencode_repository_dispatch_targets.json"
    targets = json.loads(mirror.read_text(encoding="utf-8"))["targets"]
    assert targets.count(TARGET) == 1
    assert len(targets) == len(set(targets))
