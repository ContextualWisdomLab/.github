"""Regression contract for the checked-in OpenCode gateway provider boundary."""

import json
from pathlib import Path

from scripts.ci.assert_opencode_reasoning_effort import strip_jsonc_comments

OPENCODE_CONFIG = Path("opencode.jsonc")


def _load_config() -> dict:
    """Load the repository OpenCode JSONC while preserving its public contract."""
    return json.loads(
        strip_jsonc_comments(OPENCODE_CONFIG.read_text(encoding="utf-8"))
    )


def test_root_opencode_config_excludes_dormant_direct_nvidia_provider() -> None:
    """Keep NVIDIA credentials and endpoints behind contextual-orchestrator only."""
    config_text = OPENCODE_CONFIG.read_text(encoding="utf-8")
    config = _load_config()

    assert config["enabled_providers"] == ["contextual-orchestrator"]
    assert "nvidia-nim" not in config["provider"]
    assert "https://integrate.api.nvidia.com/v1" not in config_text
    assert '"apiKey": "{env:NVIDIA_API_KEY}"' not in config_text
