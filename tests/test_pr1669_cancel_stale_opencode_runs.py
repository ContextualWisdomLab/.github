"""Permanent coverage for PR #1669's stale OpenCode cancellation owner path."""

from scripts.ci import pr_review_merge_scheduler as sched


def test_cancel_stale_opencode_runs_uses_revalidated_refs(monkeypatch):
    """Cancel only the refs returned by the live-state-aware review classifier."""
    actor_calls: list[str] = []
    cancelled_refs: list[tuple[str, str]] = []
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
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_run_refs",
        lambda refs: cancelled_refs.extend(refs),
    )

    run_ids = sched.cancel_stale_opencode_runs(
        "owner/repo",
        "OpenCode Review",
        {"number": 7, "headRefOid": "a" * 40},
        dry_run=False,
    )

    assert actor_calls == ["force-cancel-stale-opencode-review"]
    assert cancelled_refs == stale_refs
    assert run_ids == ["101", "202"]
