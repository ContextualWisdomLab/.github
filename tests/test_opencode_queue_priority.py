"""Operator runbook: prioritise the OpenCode dispatch queue without starving it."""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.ci.opencode_queue_priority import (
    PrState,
    QueuedRun,
    metrics,
    plan,
    trusted_priority,
)

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)
HEAD = "a" * 40
NEW = "b" * 40


def run(run_id: int, repo: str, pr: int, head: str = HEAD, hour: int = 6) -> QueuedRun:
    return QueuedRun(run_id, datetime(2026, 9, 29, hour, 0, tzinfo=timezone.utc), repo, pr, head)


def test_label_counts_only_when_a_maintainer_applied_it() -> None:
    assert trusted_priority("review-priority", [("review-priority", "admin")])
    assert trusted_priority("review-priority", [("review-priority", "maintain")])
    assert trusted_priority("review-priority", [("review-priority", "write")])
    # A fork author (read/triage/none) cannot jump the queue by labelling.
    assert not trusted_priority("review-priority", [("review-priority", "read")])
    assert not trusted_priority("review-priority", [("review-priority", "triage")])
    assert not trusted_priority("review-priority", [("other", "admin")])


def test_plan_keeps_priority_and_cancels_the_rest_of_current_heads() -> None:
    runs = [run(1, "o/a", 1), run(2, "o/b", 2), run(3, "o/c", 3, head=HEAD)]
    live = {
        ("o/a", 1): PrState("OPEN", HEAD, priority=True),
        ("o/b", 2): PrState("OPEN", HEAD, priority=False),
        ("o/c", 3): PrState("OPEN", NEW, priority=False),
    }
    p = plan(runs, live)
    assert [r.run_id for r in p.keep] == [1]
    assert [r.run_id for r in p.cancel_current] == [2]
    assert [r.run_id for r in p.cancel_stale] == [3]


def test_closed_or_missing_pr_is_stale_not_priority() -> None:
    runs = [run(1, "o/a", 1), run(2, "o/b", 2)]
    live = {("o/a", 1): PrState("MERGED", HEAD, priority=True)}
    p = plan(runs, live)
    assert [r.run_id for r in p.cancel_stale] == [1, 2]
    assert not p.keep


def test_metrics_surface_deferred_backlog_and_priority_position() -> None:
    runs = [run(1, "o/b", 2, hour=3), run(2, "o/a", 1, hour=5), run(3, "o/b", 3, hour=7)]
    live = {
        ("o/a", 1): PrState("OPEN", HEAD, priority=True),
        ("o/b", 2): PrState("OPEN", HEAD, priority=False),
        ("o/b", 3): PrState("OPEN", HEAD, priority=False),
    }
    m = metrics(plan(runs, live), now=NOW)
    assert m["deferred"] == 2
    assert m["oldest_deferred_hours"] == 9.0
    assert m["priority_positions"] == {"o/a#1": 2}


def test_github_transport_and_queued_identity(monkeypatch):
    """Only titled PR review runs are admitted from the mocked CLI response."""
    import json
    import subprocess
    from scripts.ci import opencode_queue_priority as queue

    calls = []
    def execute(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "receipt", "")
    monkeypatch.setattr(queue.subprocess, "run", execute)
    assert queue._gh("api", "fixture", stdin="payload") == "receipt"
    assert calls[0][1]["check"] is True
    assert calls[0][1]["input"] == "payload"
    rows = [[1, "2026-09-29T06:00:00Z", f"Review ContextualWisdomLab/a#3@{HEAD}"],
            [2, "2026-09-29T07:00:00Z", "unrelated run"]]
    monkeypatch.setattr(queue, "_gh", lambda *args, **kwargs: "\n".join(map(json.dumps, rows)))
    assert [(r.run_id, r.repo, r.pr, r.head) for r in queue.fetch_queued()] == [(1, "ContextualWisdomLab/a", 3, HEAD)]


def test_live_priority_requires_cached_maintainer_permission(monkeypatch):
    """Missing nodes, unrelated labels, and denied permissions cannot confer priority."""
    import json
    import subprocess
    from scripts.ci import opencode_queue_priority as queue

    def pr(labels, events):
        return {"pullRequest": {"state": "OPEN", "headRefOid": HEAD,
                "labels": {"nodes": [{"name": name} for name in labels]},
                "timelineItems": {"nodes": events}}}
    def event(name, actor):
        return {"label": {"name": name}, "actor": {"login": actor} if actor else None}
    events = [event("other", "ignored"), event("review-priority", None),
              event("review-priority", "writer"), event("review-priority", "writer"),
              event("review-priority", "denied")]
    permissions = []
    def github(*args, **kwargs):
        if args[1] == "graphql":
            return json.dumps({"data": {"p0": None, "p1": pr([], []),
                                       "p2": pr(["review-priority"], events)}})
        permissions.append(args[1])
        if "/denied/" in args[1]:
            raise subprocess.CalledProcessError(1, ["gh"])
        return "write\n"
    monkeypatch.setattr(queue, "_gh", github)
    states = queue.fetch_live({("o/a", 1), ("o/a", 2), ("o/a", 3)}, "review-priority")
    assert ("o/a", 1) not in states
    assert states[("o/a", 2)].priority is False
    assert states[("o/a", 3)].priority is True
    assert len(permissions) == 2
    assert queue.fetch_live(set(), "review-priority") == {}


def test_queue_cli_records_before_cancelling_only_queued_runs(monkeypatch, capsys):
    """Apply rechecks each target and cannot cancel a run that already started."""
    import pytest
    from scripts.ci import opencode_queue_priority as queue

    with pytest.raises(SystemExit) as error:
        queue.main(["--apply"])
    assert error.value.code == 2
    runs = [run(1, "o/a", 1), run(2, "o/a", 2), run(3, "o/a", 3)]
    live = {("o/a", 1): PrState("CLOSED", HEAD, False),
            ("o/a", 2): PrState("OPEN", HEAD, False),
            ("o/a", 3): PrState("CLOSED", HEAD, False)}
    monkeypatch.setattr(queue, "fetch_queued", lambda: runs)
    monkeypatch.setattr(queue, "fetch_live", lambda *_: live)
    calls = []
    def github(*args, **kwargs):
        calls.append((args, kwargs))
        if args[-1] == ".status":
            return "in_progress" if "/3" in args[1] else "queued"
        return ""
    monkeypatch.setattr(queue, "_gh", github)
    assert queue.main([]) == 0
    assert calls == []
    assert queue.main(["--post-issue", "o/a#7"]) == 0
    assert calls[-1][0][:2] == ("issue", "comment")
    calls.clear()
    assert queue.main(["--post-issue", "o/a#7", "--apply", "--include-current"]) == 0
    assert calls[0][0][:2] == ("issue", "comment")
    cancelled = [args[-1] for args, _ in calls if "POST" in args]
    assert cancelled == [f"repos/{queue.CENTRAL}/actions/runs/1/cancel",
                         f"repos/{queue.CENTRAL}/actions/runs/2/cancel"]
    assert "cancelled=2" in capsys.readouterr().out


def test_queue_entry_point_has_no_external_effects_with_empty_queue(monkeypatch):
    """An empty mocked listing executes the real script entry point safely."""
    import runpy
    import subprocess
    import sys
    from pathlib import Path
    from scripts.ci import opencode_queue_priority as queue

    monkeypatch.setattr(sys, "argv", ["queue"])
    monkeypatch.setattr(subprocess, "run", lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "", ""))
    with __import__("pytest").raises(SystemExit) as result:
        runpy.run_path(str(Path(queue.__file__)), run_name="__main__")
    assert result.value.code == 0
