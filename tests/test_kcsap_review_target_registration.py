"""K-CSAP 대상 등록은 접근 권한·정책·모델 실행 승인과 별개다."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = "ContextualWisdomLab/k-csap-skills"


def test_kcsap_review_target_is_explicit_and_unique() -> None:
    """기존 중앙 dispatch mirror에 제품을 정확히 한 번 등록한다."""
    mirror = ROOT / "scripts/ci/opencode_repository_dispatch_targets.json"
    targets = json.loads(mirror.read_text(encoding="utf-8"))["targets"]
    assert targets.count(TARGET) == 1
    assert len(targets) == len(set(targets))
