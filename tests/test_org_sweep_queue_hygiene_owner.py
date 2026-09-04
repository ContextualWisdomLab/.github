"""Pin the single-writer boundary for GitHub Actions queue hygiene."""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> str:
    """Return one trusted central workflow as UTF-8 text."""
    return (REPO_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def test_org_sweep_does_not_inventory_repository_wide_actions_runs() -> None:
    """Keep PR-head run coalescing out of the cross-repository organization sweep."""
    scheduler = _workflow("pr-review-merge-scheduler.yml")
    org_sweep = scheduler.split("  org-queue-sweep:", 1)[1]

    assert "ORG_SWEEP_STALE_QUEUE_HOURS" not in org_sweep
    assert "/actions/runs?status=${active_status}&per_page=100" not in org_sweep
    assert "for active_status in queued in_progress" not in org_sweep
    assert "revalidate_queue_cancellation.sh" not in org_sweep


def test_current_head_coalescer_owns_repo_local_exact_pr_scope() -> None:
    """Require target-repository credentials and exact live PR-head scope."""
    workflow = _workflow("current-head-run-coalescer.yml")
    helper = (
        REPO_ROOT / "scripts" / "ci" / "current_head_run_coalescer.py"
    ).read_text(encoding="utf-8")

    assert "GH_TOKEN: ${{ github.token }}" in workflow
    assert (
        "group: current-head-run-coalescer-${{ github.repository }}-${{ "
        "github.event.pull_request.number }}"
    ) in workflow
    assert (
        "EXPECTED_HEAD_REPO: ${{ github.event.pull_request.head.repo.full_name }}"
        in workflow
    )
    assert "EXPECTED_HEAD_REF: ${{ github.event.pull_request.head.ref }}" in workflow
    assert "EXPECTED_HEAD: ${{ github.event.pull_request.head.sha }}" in workflow
    assert "live_pr = _fetch_pr(repo, number)" in helper
    assert 'live_pr.get("state") != "open"' in helper
    assert (
        'raise CoalescingRefused("pull request head moved before duplicate classification")'
        in helper
    )
