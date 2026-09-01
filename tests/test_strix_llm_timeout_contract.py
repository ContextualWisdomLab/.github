"""Regression contract for the Strix model preflight request timeout."""

from __future__ import annotations

import re
from pathlib import Path


WORKFLOW_PATH = Path(__file__).parents[1] / ".github" / "workflows" / "strix.yml"


def test_strix_model_preflight_timeout_matches_upstream_default() -> None:
    """Keep model preflight finite and positive instead of cancelling it immediately."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    configured_timeouts = re.findall(
        r"(?m)^\s*export LLM_TIMEOUT=([0-9]+)\s*$",
        workflow,
    )

    assert configured_timeouts == ["300"]
