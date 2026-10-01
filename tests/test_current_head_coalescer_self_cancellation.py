"""Regression contract for the run-coalescer worker's own concurrency policy."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"
)


def test_current_head_coalescer_preserves_exact_head_scheduler_admission() -> None:
    """The scheduler queues one exact head and retires predecessors explicitly."""
    workflow_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    coalescer = workflow_text.split("\n  scan-pr-queue:\n", 1)[1]
    concurrency_block = workflow_text.split("\nconcurrency:\n", 1)[1].split(
        "\njobs:\n", 1
    )[0]
    active_lines = [
        line.strip()
        for line in concurrency_block.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]

    assert "Retire redundant queued exact-head runs" in coalescer
    assert "github.repository == 'ContextualWisdomLab/.github'" in coalescer
    assert "github.event.pull_request.head.sha" in concurrency_block
    assert "github.event.client_payload.pr_head_sha" in concurrency_block
    assert "github.event.pull_request.number" in concurrency_block
    assert not any(line.startswith("cancel-in-progress:") for line in active_lines)
    assert "queue: max" in concurrency_block

    cleanup = workflow_text.split("\n  cancel-superseded-pr-runs:\n", 1)[1].split(
        "\n  scan-pr-queue:\n", 1
    )[0]
    assert "github.event.action == 'synchronize'" in cleanup
    assert "github.event.action == 'closed'" in cleanup
    assert "actions: write" in cleanup
    assert "actions/checkout" not in cleanup
    assert "live_target_matches" in cleanup
    assert "did not reach completed/cancelled" in cleanup
