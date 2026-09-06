"""Fail-closed live PR evidence before review dispatch or exact Strix rerun."""

import pytest

from scripts.ci import pr_review_merge_scheduler as sched


HEAD = "a" * 40


def candidate():
    """Return explicit open PR metadata with canonical refs and SHAs."""
    return {
        "number": 7, "state": "OPEN", "headRefOid": HEAD,
        "baseRefOid": "b" * 40, "baseRefName": "main", "headRefName": "feature",
    }


@pytest.mark.parametrize("caller", ["opencode", "strix-dispatch", "strix-rerun"])
@pytest.mark.parametrize("state", [None, "", "CLOSED", "MERGED", "UNKNOWN", "OPEN"])
def test_live_state_gates_all_three_side_effects(monkeypatch, caller, state):
    """Only an explicitly open live PR may reach any guarded side effect."""
    pr = candidate()
    live = candidate()
    if state is None:
        live.pop("state")
    else:
        live["state"] = state
    effects = []
    monkeypatch.setattr(sched, "fetch_pr", lambda *_: [live])
    monkeypatch.setattr(sched, "require_github_actions_control_actor", lambda *_: None)
    monkeypatch.setattr(sched, "review_dispatch_admitted", lambda *_: True)
    # This suite isolates live PR state; job provenance has its own real-caller suite.
    monkeypatch.setattr(sched, "strix_rerun_identity_verified", lambda *_: True)
    monkeypatch.setattr(sched, "active_opencode_run_refs", lambda *_: ([], []))
    monkeypatch.setattr(sched, "active_review_run_refs", lambda *_, **__: ([], []))
    monkeypatch.setattr(sched, "_cancel_revalidated_review_run_refs", lambda *_: ([], []))
    monkeypatch.setattr(sched, "active_workflow_runs", lambda *_: [])
    monkeypatch.setattr(sched, "complete_paginated_pr_contexts", lambda *_: None)
    monkeypatch.setattr(sched, "matching_actions_run_id", lambda *_: None)
    monkeypatch.setattr(sched, "discover_opencode_required_run_id", lambda *_: None)
    monkeypatch.setattr(sched, "matching_actions_job_id", lambda *_: "202" if caller == "strix-rerun" else None)
    monkeypatch.setattr(sched, "repository_dispatch_target", lambda _: "ContextualWisdomLab/.github")
    monkeypatch.setattr(sched, "run_github_dispatch", lambda *_, **__: effects.append("dispatch"))
    monkeypatch.setattr(sched, "rerun_actions_job", lambda *_, **__: effects.append("rerun"))
    dispatch = sched.dispatch_opencode_review if caller == "opencode" else sched.dispatch_strix_evidence
    result = dispatch("owner/repo", "review", pr, dry_run=False)
    if state == "OPEN":
        assert result == ("rerun" if caller == "strix-rerun" else "dispatched")
        assert effects == ["rerun" if caller == "strix-rerun" else "dispatch"]
    else:
        assert result == "stale_head"
        assert effects == []


@pytest.mark.parametrize("expected,observed,accepted", [
    (HEAD, HEAD, True), (HEAD.upper(), HEAD, True),
    (HEAD, "b" * 40, False), ("", "", False), (None, None, False),
    ("bad", "bad", False), ("g" * 40, "g" * 40, False),
    ("a" * 39, "a" * 39, False), ("a" * 41, "a" * 41, False),
    (123, 123, False), (HEAD, None, False), (None, HEAD, False),
    (HEAD, "g" * 40, False), (HEAD, "", False),
])
def test_live_guard_requires_two_canonical_matching_heads(monkeypatch, expected, observed, accepted):
    """Equal empty, malformed, or non-string heads are not identity evidence."""
    pr = candidate()
    pr["headRefOid"] = expected
    monkeypatch.setattr(sched, "fetch_pr", lambda *_: [{"state": "OPEN", "headRefOid": observed}])
    assert sched.live_dispatch_head_matches("owner/repo", pr) is accepted


@pytest.mark.parametrize("rows", [[], [candidate(), candidate()]])
def test_live_guard_rejects_missing_or_ambiguous_pr(monkeypatch, rows):
    """The live lookup must identify exactly one PR."""
    monkeypatch.setattr(sched, "fetch_pr", lambda *_: rows)
    assert not sched.live_dispatch_head_matches("owner/repo", candidate())


def test_exact_graphql_fetch_requests_pr_state(monkeypatch):
    """The actual single-PR query must request state in its shared fragment."""
    def graphql(query, **fields):
        fragment = query.split("fragment SchedulerPullRequestFields on PullRequest {", 1)[1]
        assert "  state" in fragment.split("  author", 1)[0].splitlines()
        assert fields == {"owner": "owner", "name": "repo", "number": 7}
        return {"data": {"repository": {"pullRequest": {**candidate(), "state": "CLOSED"}}}}

    monkeypatch.setattr(sched, "gh_graphql", graphql)
    monkeypatch.setattr(sched, "complete_all_pr_reviews", lambda *_: None)
    monkeypatch.setattr(sched, "enrich_rest_mergeable_states", lambda *_: None)
    assert sched.fetch_pr("owner/repo", 7)[0]["state"] == "CLOSED"
    assert not sched.live_dispatch_head_matches("owner/repo", candidate())


@pytest.mark.parametrize("state,normalized", [("open", "OPEN"), ("closed", "CLOSED"), (None, "")])
def test_rest_normalization_preserves_state_without_open_default(monkeypatch, state, normalized):
    """REST fallback must retain closure and must not manufacture open state."""
    pr = {"number": 7, "head": {"sha": HEAD}}
    if state is not None:
        pr["state"] = state
    responses = {
        "repos/owner/repo/pulls/7": pr,
        f"repos/owner/repo/commits/{HEAD}/check-runs?per_page=100": {},
        f"repos/owner/repo/commits/{HEAD}/check-suites?per_page=100": {},
        f"repos/owner/repo/commits/{HEAD}/status": {},
        "repos/owner/repo/pulls/7/files?per_page=20": [],
    }
    monkeypatch.setattr(sched, "gh_api_json", lambda endpoint: responses[endpoint])
    monkeypatch.setattr(sched, "fetch_all_pr_reviews_rest", lambda *_: [])
    assert sched.fetch_pr_rest("owner/repo", 7)[0]["state"] == normalized
