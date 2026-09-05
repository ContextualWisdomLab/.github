"""Regression contract for the run-coalescer worker's own concurrency policy."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "current-head-run-coalescer.yml"


def test_current_head_coalescer_admits_live_head_before_native_concurrency() -> None:
    """PR-scoped concurrency retires stale queued heads before job admission."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    coalescer = workflow_text.split("\n  coalesce:\n", 1)[1]
    concurrency_block = workflow_text.split("\nconcurrency:\n", 1)[1].split(
        "\njobs:\n", 1
    )[0]
    active_lines = [
        line.strip()
        for line in concurrency_block.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "admit-current-head:" not in workflow_text
    assert "id: live-head" in coalescer
    assert coalescer.count("if: steps.live-head.outputs.admitted == 'true'") == 2
    assert "github.event.pull_request.head.sha" not in concurrency_block
    assert "github.event.pull_request.number" in concurrency_block
    assert "cancel-in-progress: true" in active_lines
    assert "queue: max" not in workflow_text
