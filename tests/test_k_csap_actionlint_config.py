"""K-CSAP canonical actionlint 설정의 자동 발견과 라벨 범위를 검증한다."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_config_registers_only_reviewed_custom_labels():
    """공유 라벨을 보존하고 K-CSAP 라벨만 추가하며 wildcard는 거부한다."""
    config = ROOT / ".github/actionlint.yaml"
    assert config.is_file(), "canonical actionlint config missing"
    assert yaml.safe_load(config.read_text(encoding="utf-8")) == {
        "self-hosted-runner": {
            "labels": ["cwlab-ci-isolated", "cwlab-control", "k-csap-isolated"]
        }
    }
