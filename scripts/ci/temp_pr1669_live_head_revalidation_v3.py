#!/usr/bin/env python3
"""Finish PR #1669 repair after v2, adapting legacy synthetic SHA fixtures."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
V2 = ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v2.py"
TESTS = ROOT / "tests/test_pr_review_merge_scheduler.py"
SELF = Path(__file__).resolve()


def inject_once(text: str, name: str) -> str:
    """Keep a legacy filter test focused on filtering rather than SHA syntax."""
    anchor = f"def {name}(monkeypatch):\n"
    addition = '    monkeypatch.setattr(sched, "validate_git_sha", lambda value: str(value))\n'
    if anchor not in text:
        raise RuntimeError(f"missing legacy test anchor: {name}")
    if anchor + addition in text:
        return text
    if text.count(anchor) != 1:
        raise RuntimeError(f"ambiguous legacy test anchor: {name}")
    return text.replace(anchor, anchor + addition, 1)


def main() -> int:
    """Run v2 transformation, adapt legacy fixtures, and remove this helper."""
    subprocess.run([sys.executable, str(V2)], cwd=ROOT, check=True)
    text = TESTS.read_text(encoding="utf-8")
    for name in (
        "test_stale_opencode_run_ids_filters_current_head_and_missing_ids",
        "test_workflow_run_filters_skip_mismatched_workflow_and_current_head_other_pr",
    ):
        text = inject_once(text, name)
    TESTS.write_text(text, encoding="utf-8")
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
