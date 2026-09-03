"""Regression contract for the run-coalescer worker's own concurrency policy."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "current-head-run-coalescer.yml"


def test_current_head_coalescer_cannot_cancel_its_active_cleanup_worker() -> None:
    """Push bursts must queue the next cleanup instead of killing the active cleanup.

    A plain cancel-in-progress: false only protects a RUNNING job -- GitHub
    concurrency groups still retain just one PENDING (queued) run and
    silently replace it whenever another run enters the same group,
    regardless of cancel-in-progress. queue: max is the feature that keeps
    every pending run queued (up to 100) instead of evicting all but the
    latest, so it must live on the job-level concurrency block, not a
    workflow-level cancel-in-progress: false.
    """
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    concurrency_block = workflow_text.split("\n    concurrency:", 1)[1].split("\n    runs-on:", 1)[0]
    active_lines = [
        line.strip()
        for line in concurrency_block.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "queue: max" in active_lines
    assert "cancel-in-progress: true" not in active_lines
