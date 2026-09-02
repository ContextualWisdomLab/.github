"""Permanent coverage for PR #1669's stale OpenCode cancellation owner path."""

from scripts.ci import pr_review_merge_scheduler as sched


def test_cancel_stale_opencode_runs_uses_revalidated_refs(monkeypatch):
    """Revalidate every candidate and cancel only refs still proven stale."""
    actor_calls: list[str] = []
    revalidated: list[tuple[str, str, int, str, str]] = []
    cancelled: list[tuple[str, list[str]]] = []
    stale_refs = [("owner/repo", "101"), ("owner/repo", "202")]

    monkeypatch.setattr(
        sched,
        "require_github_actions_control_actor",
        lambda action: actor_calls.append(action),
    )
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda _repo, _workflow, _pr: ([], stale_refs),
    )

    def still_superseded(repo, workflow, number, run_repo, run_id):
        revalidated.append((repo, workflow, number, run_repo, run_id))
        return True

    monkeypatch.setattr(sched, "_review_run_still_superseded", still_superseded)
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, list(run_ids))),
    )

    run_ids = sched.cancel_stale_opencode_runs(
        "owner/repo",
        "OpenCode Review",
        {"number": 7, "headRefOid": "a" * 40},
        dry_run=False,
    )

    assert actor_calls == ["force-cancel-stale-opencode-review"]
    assert sorted(revalidated) == [
        ("owner/repo", "OpenCode Review", 7, "owner/repo", "101"),
        ("owner/repo", "OpenCode Review", 7, "owner/repo", "202"),
    ]
    assert sorted(cancelled) == [
        ("owner/repo", ["101"]),
        ("owner/repo", ["202"]),
    ]
    assert sorted(run_ids) == ["101", "202"]


def test_cancel_stale_opencode_runs_preserves_failed_cancellation(monkeypatch):
    """Keep a stale review active when GitHub rejects its cancellation."""
    stale_refs = [("owner/repo", "101"), ("owner/repo", "202")]
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda _repo, _workflow, _pr: ([], stale_refs),
    )
    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)

    def cancel(_repo, run_ids):
        run_id = str(run_ids[0])
        return {run_id: "GitHub rejected cancellation"} if run_id == "101" else {}

    monkeypatch.setattr(sched, "force_cancel_workflow_runs", cancel)

    run_ids = sched.cancel_stale_opencode_runs(
        "owner/repo",
        "OpenCode Review",
        {"number": 7, "headRefOid": "a" * 40},
        dry_run=False,
    )

    assert run_ids == ["202"]


def test_cancel_stale_pr_runs_preserves_failed_cancellation(monkeypatch):
    """Do not report a direct stale run cancelled when the API call failed."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(sched, "stale_pr_run_ids", lambda _repo, _pr: ["101", "202"])
    monkeypatch.setattr(sched, "_direct_pr_run_still_superseded", lambda *_args: True)

    def cancel(_repo, run_ids):
        run_id = str(run_ids[0])
        return {run_id: "GitHub rejected cancellation"} if run_id == "101" else {}

    monkeypatch.setattr(sched, "force_cancel_workflow_runs", cancel)

    run_ids = sched.cancel_stale_pr_runs(
        "owner/repo",
        {"number": 7, "headRefOid": "a" * 40},
        dry_run=False,
    )

    assert run_ids == ["202"]
