"""Regression contracts for removing scheduler-created source-neutral commits."""

from __future__ import annotations

import json

import pytest

from scripts.ci import pr_review_merge_scheduler_core as sched
from tests.test_pr_review_merge_scheduler import (
    inspect,
    last_push_approval_candidate,
    make_pr,
)


def test_last_push_approval_waits_without_same_tree_head_mutation(monkeypatch):
    """Last-push protection cannot be satisfied by manufacturing a new commit."""
    monkeypatch.setattr(
        sched,
        "run",
        lambda *args, **kwargs: pytest.fail("last-push approval must not mutate the head"),
    )

    decision = inspect(last_push_approval_candidate())

    assert decision.action == "wait"
    assert "independent approval on the unchanged head" in decision.reason
    assert "source-neutral head refresh is forbidden" in decision.reason


def test_startup_failure_is_reported_without_same_tree_head_mutation(monkeypatch):
    """A pre-job failure reports exact run evidence without manufacturing a new head."""
    head_sha = "a" * 40
    run = {
        "id": 92,
        "workflow_id": 12,
        "name": "CodeQL PR",
        "path": ".github/workflows/codeql-pr.yml",
        "event": "pull_request",
        "head_sha": head_sha,
        "status": "completed",
        "conclusion": "startup_failure",
        "created_at": "2026-09-12T00:00:00Z",
    }
    monkeypatch.setattr(
        sched,
        "run_github_read",
        lambda _args: json.dumps({"workflow_runs": [run]}),
    )
    monkeypatch.setattr(sched, "actions_run_has_no_jobs", lambda _repo, _run_id: True)
    monkeypatch.setattr(
        sched,
        "run",
        lambda *_args, **_kwargs: pytest.fail("startup-failure reporting must not mutate GitHub"),
    )

    assert sched.recover_current_head_startup_failures(
        "owner/repo", make_pr(headRefOid=head_sha), dry_run=False
    ) == [92]
