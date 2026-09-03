"""Regression contracts for the run-coalescer worker's concurrency policy."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "current-head-run-coalescer.yml"


def test_current_head_coalescer_preserves_active_worker_and_latest_pending_event() -> None:
    """Push bursts must keep the active cleanup plus the latest pending trigger."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    concurrency_block = workflow_text.split("concurrency:", 1)[1].split("\npermissions:", 1)[0]
    active_lines = [
        line.strip()
        for line in concurrency_block.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "cancel-in-progress: false" in active_lines
    assert "cancel-in-progress: true" not in active_lines
    assert "queue: single" in active_lines
    assert "queue: max" not in active_lines
