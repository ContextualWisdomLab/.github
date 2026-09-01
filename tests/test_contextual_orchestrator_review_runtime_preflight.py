"""Collect the established runtime-preflight regressions with one repaired oracle.

The regression corpus remains byte-for-byte in the adjacent non-collectable
case module. This collection shim re-exports every existing test except the
obsolete constructor-text assertion, then replaces that assertion with the
actual bounded-retry and deadline-free serving contract introduced for the
DeepSeek incident.
"""

from __future__ import annotations

import runpy
from pathlib import Path


_CASES_PATH = Path(__file__).with_name(
    "_contextual_orchestrator_review_runtime_preflight_cases.py"
)
_CASES = runpy.run_path(str(_CASES_PATH))
_OBSOLETE_TEST = "test_preflight_transport_has_no_inference_timeout_and_is_provider_neutral"

for _name, _value in _CASES.items():
    if not _name.startswith("__") and _name != _OBSOLETE_TEST:
        globals()[_name] = _value


def test_preflight_transport_has_no_inference_timeout_and_uses_bounded_retry() -> None:
    """Review inference is deadline-free while preflight retries once."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")

    assert "REVIEW_MAX_OUTPUT_TOKENS = 4096" in launcher
    assert "REVIEW_TEMPERATURE = 1.0" in launcher
    assert "REVIEW_PREFLIGHT_TIMEOUT_SECONDS" not in launcher
    assert "REVIEW_PREFLIGHT_TRANSIENT_RETRIES = 1" in launcher
    assert launcher.count("timeout=None") == 2
    assert "max_retries=REVIEW_PREFLIGHT_TRANSIENT_RETRIES" in launcher
    assert "temperature=REVIEW_TEMPERATURE" in launcher
