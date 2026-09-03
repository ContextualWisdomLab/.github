"""Regression contract for the run-coalescer worker's own concurrency policy."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "current-head-run-coalescer.yml"


def test_current_head_coalescer_cannot_cancel_its_active_cleanup_worker() -> None:
    """Push bursts must queue the next cleanup instead of killing the active cleanup.

    A bare cancel-in-progress: false only protects a RUNNING job -- GitHub
    concurrency groups still evict a PENDING (queued) run the instant another run
    enters the same group, regardless of cancel-in-progress. Verified 2026-09-03:
    PR #1741's required-review checks sat stuck queued because the coalescer never
    once got a runner during a push burst. queue: max (not cancel-in-progress alone)
    is what actually keeps a queued cleanup alive.
    """
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    concurrency_block = workflow_text.split("concurrency:", 1)[1].split("runs-on:", 1)[0]
    active_lines = [
        line.strip()
        for line in concurrency_block.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "queue: max" in active_lines
    assert "cancel-in-progress: true" not in active_lines
