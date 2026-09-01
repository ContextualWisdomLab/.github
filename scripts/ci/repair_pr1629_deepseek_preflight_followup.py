#!/usr/bin/env python3
"""Align the legacy preflight regression before running the PR #1629 repair."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME_TEST = ROOT / "tests/test_contextual_orchestrator_review_runtime_preflight.py"
DRIVER = ROOT / "scripts/ci/repair_pr1629_deepseek_preflight.py"
SELF = Path(__file__).resolve()

OLD = '''def test_preflight_transport_has_no_inference_timeout_and_is_provider_neutral() -> None:
    launcher = _LAUNCHER.read_text(encoding="utf-8")

    assert "REVIEW_MAX_OUTPUT_TOKENS = 4096" in launcher
    assert "REVIEW_TEMPERATURE = 1.0" in launcher
    assert "REVIEW_PREFLIGHT_TIMEOUT_SECONDS" not in launcher
    assert "ModelClient(\\n        timeout=" not in launcher
    assert "max_retries=0" in launcher
    assert "temperature=REVIEW_TEMPERATURE" in launcher
'''

NEW = '''def test_preflight_transport_has_no_inference_timeout_and_uses_bounded_retry() -> None:
    """Review inference is deadline-free while preflight gets one transient retry."""
    launcher = _LAUNCHER.read_text(encoding="utf-8")

    assert "REVIEW_MAX_OUTPUT_TOKENS = 4096" in launcher
    assert "REVIEW_TEMPERATURE = 1.0" in launcher
    assert "REVIEW_PREFLIGHT_TIMEOUT_SECONDS" not in launcher
    assert "REVIEW_PREFLIGHT_TRANSIENT_RETRIES = 1" in launcher
    assert launcher.count("timeout=None") == 2
    assert "max_retries=REVIEW_PREFLIGHT_TRANSIENT_RETRIES" in launcher
    assert "temperature=REVIEW_TEMPERATURE" in launcher
'''


def main() -> int:
    """Patch the contradictory legacy oracle, run the existing transaction, self-delete."""
    text = RUNTIME_TEST.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise RuntimeError(f"legacy preflight regression anchor count={count}; refusing stale rewrite")
    RUNTIME_TEST.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")

    subprocess.run([sys.executable, str(DRIVER)], cwd=ROOT, check=True)
    SELF.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
