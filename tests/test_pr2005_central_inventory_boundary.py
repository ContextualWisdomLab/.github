"""Regression contracts for PR #2005's central review inventory boundary."""

from scripts.ci import pr_review_merge_scheduler_core as scheduler_core


def inspect_stacked_pull_request(repository, dispatch_repository, monkeypatch):
    """Return the stale-run cleanup calls for one read-only stacked PR inspection."""
    cleanup_calls = []
    monkeypatch.setenv(
        "SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY",
        dispatch_repository,
    )
    monkeypatch.setattr(
        scheduler_core,
        "cancel_stale_pr_runs",
        lambda target_repository, pull_request, *, dry_run: cleanup_calls.append(
            (target_repository, dry_run)
        ),
    )
    pull_request = {
        "number": 1,
        "isDraft": False,
        "baseRefName": "feature-base",
        "headRefOid": "a" * 40,
        "files": {"totalCount": 1, "nodes": [{"path": "README.md"}]},
        "reviews": {"nodes": []},
        "reviewThreads": {"nodes": []},
        "statusCheckRollup": {"contexts": {"nodes": []}},
        "autoMergeRequest": None,
    }

    scheduler_core.inspect_pr(
        repository,
        pull_request,
        dry_run=True,
        trigger_reviews=False,
        enable_auto_merge_flag=False,
        update_branches=False,
        workflow="OpenCode Review",
        security_workflow="Strix Security Scan",
        base_branch="main",
    )
    return cleanup_calls


def test_central_dispatch_retains_target_cleanup(monkeypatch):
    """Cross-repository dispatch must still invoke target-owned stale cleanup."""
    cleanup_calls = inspect_stacked_pull_request(
        "owner/repo",
        "ContextualWisdomLab/.github",
        monkeypatch,
    )

    assert cleanup_calls == [("owner/repo", True)]


def test_same_repository_dispatch_keeps_unfiltered_cleanup_case_insensitively(
    monkeypatch,
):
    """Repository identity casing must not narrow same-repository cleanup."""
    cleanup_calls = inspect_stacked_pull_request(
        "owner/repo",
        "OWNER/REPO",
        monkeypatch,
    )

    assert cleanup_calls == [("owner/repo", True)]


def test_cancel_stale_pr_runs_applies_central_review_filter_internally(monkeypatch):
    """Existing callers keep their signature while cancellation scopes authority."""
    captured_exclusions = []
    monkeypatch.setenv(
        "SCHEDULER_REQUIRED_WORKFLOW_REPOSITORY",
        "ContextualWisdomLab/.github",
    )
    monkeypatch.setattr(
        scheduler_core,
        "require_github_actions_control_actor",
        lambda _action: None,
    )

    def stale_run_ids(_repo, _pull_request, *, excluded_workflows=frozenset()):
        captured_exclusions.append(excluded_workflows)
        return []

    monkeypatch.setattr(scheduler_core, "stale_pr_run_ids", stale_run_ids)

    assert scheduler_core.cancel_stale_pr_runs(
        "owner/repo",
        {"number": 1, "headRefOid": "a" * 40},
        dry_run=False,
    ) == []
    assert captured_exclusions == [
        frozenset(scheduler_core.OPENCODE_WORKFLOW_NAMES)
    ]


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
