"""Failure-isolation regressions for central review-dispatch retirement."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "ci"
    / "closed_review_dispatch_reaper.py"
)
spec = importlib.util.spec_from_file_location("closed_review_dispatch_reaper_failures", SCRIPT)
assert spec is not None and spec.loader is not None
reaper = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reaper
spec.loader.exec_module(reaper)


def test_one_cancellation_failure_does_not_block_later_stale_run() -> None:
    """A GitHub cancellation race is isolated and later stale runs still retire."""
    runs = [
        {
            "id": 11,
            "name": "OpenCode Review Dispatch",
            "display_title": "OpenCode Review Dispatch ContextualWisdomLab/x#1@" + "a" * 40,
            "event": "repository_dispatch",
        },
        {
            "id": 12,
            "name": "Required Noema Review",
            "display_title": "Required Noema Review ContextualWisdomLab/y#2@" + "b" * 40,
            "event": "repository_dispatch",
        },
    ]
    cancelled: list[str] = []

    def cancel(run_id: str) -> None:
        if run_id == "11":
            raise RuntimeError("already completed")
        cancelled.append(run_id)

    summary = reaper.reap_review_dispatches(
        runs,
        fetch_pr=lambda _repo, _pr: {"state": "closed", "head": {"sha": "f" * 40}},
        cancel=cancel,
    )

    assert cancelled == ["12"]
    assert summary.cancelled_closed == 1
    assert summary.cancellation_failed == 1
