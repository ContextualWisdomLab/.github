"""Regression contract for the run-coalescer worker's own concurrency policy."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = (
    REPOSITORY_ROOT / ".github" / "workflows" / "pr-review-merge-scheduler.yml"
)


def test_current_head_coalescer_shares_pr_scoped_scheduler_admission() -> None:
    """The integrated step reuses PR-scoped scheduler admission and its runner."""
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
    assert "github.event.pull_request.head.sha" not in concurrency_block
    assert "github.event.pull_request.number" in concurrency_block
    normalized_concurrency = " ".join(active_lines)
    assert "cancel-in-progress: >- ${{" in normalized_concurrency
    assert "github.event_name == 'pull_request_target'" in normalized_concurrency
    assert "github.event_name == 'repository_dispatch'" in normalized_concurrency
    assert "github.event.review.state == 'approved'" in normalized_concurrency
    assert "github.event.review.state == 'changes_requested'" in normalized_concurrency
    assert "queue: max" not in workflow_text
