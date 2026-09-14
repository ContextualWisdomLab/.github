"""Collect the current runtime-preflight regressions.

Historical incidents remain in ADR/doctoring records. The adjacent case module
contains only executable expectations that match the present one-shot,
provider-default contract, so collection no longer suppresses tests by legacy
function name or prefix.
"""

from __future__ import annotations

import runpy
from pathlib import Path


_CASES_PATH = Path(__file__).with_name(
    "_contextual_orchestrator_review_runtime_preflight_cases.py"
)
_CASES = runpy.run_path(str(_CASES_PATH))
_LAUNCHER = Path(__file__).resolve().parents[1] / "scripts/ci/contextual_orchestrator_review_launcher.py"


for _name, _value in _CASES.items():
    if _name.startswith("test_"):
        globals()[_name] = _value


def test_preflight_transport_has_no_inference_timeout_or_compute_defaults() -> None:
    """Central review inference supplies no repository-authored TTC policy."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")

    assert "REVIEW_PREFLIGHT_TIMEOUT_SECONDS" not in launcher
    assert "REVIEW_PREFLIGHT_TRANSIENT_RETRIES" not in launcher
    assert "REVIEW_MAX_OUTPUT_TOKENS" not in launcher
    assert "REVIEW_TEMPERATURE" not in launcher
    assert "REVIEW_PREFLIGHT_BASE_TOKENS" not in launcher
    assert "REVIEW_PREFLIGHT_ESCALATED_TOKENS" not in launcher
    assert launcher.count("timeout=None") == 2
    assert launcher.count("max_retries=0") == 2
    assert "max_output_tokens=" not in launcher
    assert "temperature=" not in launcher
