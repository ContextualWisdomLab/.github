"""Regression contracts for PR #2005's central review inventory boundary."""

from scripts.ci import pr_review_merge_scheduler_core as scheduler_core


def test_central_review_filter_preserves_target_security_runs(monkeypatch):
    """Central review ownership must not preserve unrelated stale target runs."""
    current_head = "a" * 40
    stale_head = "b" * 40
    workflow_runs = [
        {
            "id": 101,
            "name": "Required OpenCode Review owner/repo#1@" + stale_head,
            "head_sha": stale_head,
            "pull_requests": [{"number": 1}],
        },
        {
            "id": 102,
            "name": "Python Security",
            "head_sha": stale_head,
            "pull_requests": [{"number": 1}],
        },
        {
            "id": 103,
            "name": "CodeQL",
            "head_sha": stale_head,
            "pull_requests": [{"number": 1}],
        },
    ]
    monkeypatch.setattr(
        scheduler_core,
        "active_workflow_runs",
        lambda _repo, _statuses: workflow_runs,
    )

    assert scheduler_core.stale_pr_run_ids(
        "owner/repo",
        {"number": 1, "headRefOid": current_head},
        excluded_workflows=frozenset(scheduler_core.OPENCODE_WORKFLOW_NAMES),
    ) == ["102", "103"]


def test_central_review_filter_matches_bare_and_rendered_names(monkeypatch):
    """Both GitHub workflow names and rendered run names use central authority."""
    current_head = "a" * 40
    stale_head = "b" * 40
    workflow_runs = [
        {
            "id": 201,
            "name": "OpenCode Review",
            "head_sha": stale_head,
            "pull_requests": [{"number": 1}],
        },
        {
            "id": 202,
            "name": "OpenCode Review Dispatch owner/repo#1@" + stale_head,
            "head_sha": stale_head,
            "pull_requests": [{"number": 1}],
        },
    ]
    monkeypatch.setattr(
        scheduler_core,
        "active_workflow_runs",
        lambda _repo, _statuses: workflow_runs,
    )

    assert scheduler_core.stale_pr_run_ids(
        "owner/repo",
        {"number": 1, "headRefOid": current_head},
        excluded_workflows=frozenset(scheduler_core.OPENCODE_WORKFLOW_NAMES),
    ) == []
