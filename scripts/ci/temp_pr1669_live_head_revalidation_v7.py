#!/usr/bin/env python3
"""Refresh legacy scheduler fixtures after live stale-run revalidation lands."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
SELF = Path(__file__).resolve()
PATCH = '    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)\n'


def insert_after_signature(text: str, signature: str) -> str:
    """Insert one compatibility monkeypatch after one exact legacy test signature."""
    anchor = signature + "\n"
    if anchor + PATCH in text:
        return text
    if text.count(anchor) != 1:
        raise RuntimeError(f"expected exactly one legacy test signature: {signature}")
    return text.replace(anchor, anchor + PATCH, 1)


def main() -> int:
    """Preserve legacy cancellation intent while dedicated tests cover live revalidation."""
    text = TESTS.read_text(encoding="utf-8")
    text = insert_after_signature(
        text,
        "def test_dispatch_opencode_review_force_cancels_same_pr_old_head_runs(monkeypatch):",
    )
    text = insert_after_signature(
        text,
        "def test_dispatch_strix_cancels_stale_central_run_and_keeps_current(monkeypatch, capsys):",
    )
    TESTS.write_text(text, encoding="utf-8")
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
