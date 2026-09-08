"""Permanent regression coverage for PR #1669's headRefOid cancellation bug.

Reproduces the live ``ContextualWisdomLab/naruon#1528`` incident: Strix run
``33581213829`` for head ``cf472cf77fb93325858f485a22e967449d7c387a`` was
force-cancelled while it was the PR's sole, unchanged current head, because
``stale_pr_run_ids()`` and ``active_review_run_refs()`` computed the expected
head as ``str(pr.get("headRefOid") or "").lower()`` -- a missing/falsy
``headRefOid`` silently coerced to ``""``, which never equals a real 40-hex
``head_sha``, so every active run for the PR (including the true current-head
run) was misclassified as stale. See
``docs/doctoring/scheduler-stale-headrefoid-cancellation.md``.
"""

from scripts.ci import pr_review_merge_scheduler as sched

NARUON_REPO = "ContextualWisdomLab/naruon"
NARUON_PR_NUMBER = 1528
NARUON_RUN_ID = 33581213829
NARUON_HEAD_SHA = "cf472cf77fb93325858f485a22e967449d7c387a"


def test_stale_pr_run_ids_preserves_current_head_run_when_head_ref_oid_missing(monkeypatch):
    """A missing headRefOid must not classify the live current-head run stale."""
    monkeypatch.setattr(
        sched,
        "active_workflow_runs",
        lambda *_args, **_kwargs: [
            {
                "id": NARUON_RUN_ID,
                "head_sha": NARUON_HEAD_SHA,
                "pull_requests": [{"number": NARUON_PR_NUMBER}],
            }
        ],
    )

    stale = sched.stale_pr_run_ids(
        NARUON_REPO, {"number": NARUON_PR_NUMBER, "headRefOid": None}
    )

    assert stale == []


def test_active_review_run_refs_preserves_current_head_run_when_head_ref_oid_missing(
    monkeypatch,
):
    """A missing headRefOid must not classify the live current-head review run stale."""
    monkeypatch.setattr(
        sched,
        "active_workflow_runs",
        lambda *_args, **_kwargs: [
            {
                "id": NARUON_RUN_ID,
                "event": "pull_request",
                "name": "Strix Security Scan",
                "head_sha": NARUON_HEAD_SHA,
                "pull_requests": [{"number": NARUON_PR_NUMBER}],
            }
        ],
    )

    current, stale = sched.active_review_run_refs(
        NARUON_REPO,
        "Strix Security Scan",
        {"number": NARUON_PR_NUMBER, "headRefOid": None},
        run_title="Strix Security Scan",
        workflow_aliases=frozenset({"Strix Security Scan"}),
    )

    assert current == []
    assert stale == []


def test_cancel_stale_pr_runs_issues_no_cancel_call_when_head_ref_oid_missing(monkeypatch):
    """A missing headRefOid must yield no stale candidate before the second,
    live-revalidation safety net ever runs -- isolated here (by forcing that
    net to say "still superseded") so this test depends only on the
    ``stale_pr_run_ids`` guard under test, not on the independent live re-fetch."""
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda _action: None)
    monkeypatch.setattr(
        sched,
        "active_workflow_runs",
        lambda *_args, **_kwargs: [
            {
                "id": NARUON_RUN_ID,
                "head_sha": NARUON_HEAD_SHA,
                "pull_requests": [{"number": NARUON_PR_NUMBER}],
            }
        ],
    )
    monkeypatch.setattr(sched, "_direct_pr_run_still_superseded", lambda *_a, **_k: True)
    cancelled = []
    monkeypatch.setattr(
        sched,
        "force_cancel_workflow_runs",
        lambda *args: cancelled.append(args),
    )

    run_ids = sched.cancel_stale_pr_runs(
        NARUON_REPO,
        {"number": NARUON_PR_NUMBER, "headRefOid": None},
        dry_run=False,
    )

    assert run_ids == []
    assert cancelled == []


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

    def cancel(repo, run_ids):
        cancelled.append((repo, list(run_ids)))
        return {}

    monkeypatch.setattr(sched, "force_cancel_workflow_runs", cancel)

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
