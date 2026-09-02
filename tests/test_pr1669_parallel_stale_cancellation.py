"""Coverage for PR #1669's parallel destructive-boundary revalidation paths."""

from scripts.ci import pr_review_merge_scheduler as sched


def test_multiple_direct_candidates_cancel_only_after_live_revalidation(monkeypatch):
    """The direct multi-candidate executor cancels every independently proven stale run."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(sched, "stale_pr_run_ids", lambda *_args, **_kwargs: ["91", "92"])
    monkeypatch.setattr(sched, "_direct_pr_run_still_superseded", lambda *_args: True)
    cancelled: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, tuple(run_ids))),
    )

    result = sched.cancel_stale_pr_runs(
        "owner/repo", {"number": 7, "headRefOid": "a" * 40}, dry_run=False
    )

    assert result == ["91", "92"]
    assert sorted(cancelled) == [
        ("owner/repo", ("91",)),
        ("owner/repo", ("92",)),
    ]


def test_multiple_review_candidates_cancel_only_after_live_revalidation(monkeypatch):
    """The review multi-candidate executor cancels every independently proven stale run."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_opencode_run_refs",
        lambda *_args, **_kwargs: (
            [],
            [("ContextualWisdomLab/.github", "93"), ("ContextualWisdomLab/.github", "94")],
        ),
    )
    monkeypatch.setattr(sched, "_review_run_still_superseded", lambda *_args: True)
    cancelled: list[tuple[str, tuple[str, ...]]] = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda repo, run_ids: cancelled.append((repo, tuple(run_ids))),
    )

    result = sched.cancel_stale_opencode_runs(
        "owner/repo",
        "OpenCode Review",
        {"number": 7, "headRefOid": "a" * 40},
        dry_run=False,
    )

    assert result == ["93", "94"]
    assert sorted(cancelled) == [
        ("ContextualWisdomLab/.github", ("93",)),
        ("ContextualWisdomLab/.github", ("94",)),
    ]
