#!/usr/bin/env python3
"""Finish PR #1669 repair with generated nested-function docstring coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
V3 = ROOT / "scripts/ci/temp_pr1669_live_head_revalidation_v3.py"
SCHEDULER = ROOT / "scripts/ci/pr_review_merge_scheduler.py"
SELF = Path(__file__).resolve()


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    """Replace exactly one generated scheduler fragment."""
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one generated anchor, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    """Run v3 transformation, add nested docstrings, and remove this helper."""
    subprocess.run([sys.executable, str(V3)], cwd=ROOT, check=True)
    text = SCHEDULER.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    def cancel_one(run_id: str) -> str | None:\n        if not _direct_pr_run_still_superseded(repo, number, run_id):",
        "    def cancel_one(run_id: str) -> str | None:\n        \"\"\"Revalidate and cancel one direct workflow-run candidate when still stale.\"\"\"\n        if not _direct_pr_run_still_superseded(repo, number, run_id):",
        label="direct cancellation docstring",
    )
    text = replace_once(
        text,
        "    def cancel_one(run_ref: tuple[str, str]) -> str | None:\n        run_repo, run_id = run_ref",
        "    def cancel_one(run_ref: tuple[str, str]) -> str | None:\n        \"\"\"Revalidate and cancel one review-run candidate when still stale.\"\"\"\n        run_repo, run_id = run_ref",
        label="review cancellation docstring",
    )
    SCHEDULER.write_text(text, encoding="utf-8")
    SELF.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
