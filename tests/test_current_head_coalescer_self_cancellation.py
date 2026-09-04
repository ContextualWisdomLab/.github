"""Regression contract for the run-coalescer worker's own concurrency policy."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "current-head-run-coalescer.yml"


def test_current_head_coalescer_admits_live_head_before_native_concurrency() -> None:
    """A stale event cannot enter the PR queue and cancel the live cleanup."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    admission = workflow_text.split("  admit-current-head:\n", 1)[1].split(
        "\n  coalesce:\n", 1
    )[0]
    coalescer = workflow_text.split("\n  coalesce:\n", 1)[1]
    concurrency_block = coalescer.split("concurrency:", 1)[1].split("runs-on:", 1)[0]
    active_lines = [
        line.strip()
        for line in concurrency_block.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "live-head" in admission
    assert "needs: admit-current-head" in coalescer
    assert "if: needs.admit-current-head.outputs.admitted == 'true'" in coalescer
    assert "cancel-in-progress: true" in active_lines
    assert "queue: max" not in workflow_text
