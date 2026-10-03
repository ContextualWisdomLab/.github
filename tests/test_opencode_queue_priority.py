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
