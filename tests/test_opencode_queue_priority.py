"""Operator runbook: prioritise the OpenCode dispatch queue without starving it."""

from __future__ import annotations

<<<<<<< HEAD
from datetime import datetime, timezone

=======
import json
import runpy
import subprocess
import sys
from datetime import datetime, timezone

import pytest

import scripts.ci.opencode_queue_priority as queue_priority
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
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
<<<<<<< HEAD
=======

def test_fetch_queued_keeps_only_bound_pull_request_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Malformed display titles cannot enter the cancellation plan."""
    rows = [
        [41, "2026-09-30T10:00:00Z", "ContextualWisdomLab/naruon#1829@abcdef0"],
        [42, "2026-09-30T10:01:00Z", "unbound dispatch"],
    ]
    monkeypatch.setattr(queue_priority, "_gh", lambda *args, **kwargs: "\n".join(map(json.dumps, rows)))

    queued = queue_priority.fetch_queued()

    assert queued == [QueuedRun(
        41,
        datetime(2026, 9, 30, 10, 0, tzinfo=timezone.utc),
        "ContextualWisdomLab/naruon",
        1829,
        "abcdef0",
    )]


def test_fetch_live_requires_a_trusted_label_actor_and_caches_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A label is priority only when its actor has repository write authority."""
    graphql = {
        "data": {
            "p0": {"pullRequest": {
                "state": "OPEN",
                "headRefOid": HEAD,
                "labels": {"nodes": [{"name": "review-priority"}]},
                "timelineItems": {"nodes": [
                    {"label": {"name": "other"}, "actor": {"login": "maintainer"}},
                    {"label": {"name": "review-priority"}, "actor": None},
                    {"label": {"name": "review-priority"}, "actor": {"login": "maintainer"}},
                    {"label": {"name": "review-priority"}, "actor": {"login": "maintainer"}},
                ]},
            }},
            "p1": {"pullRequest": {
                "state": "OPEN",
                "headRefOid": NEW,
                "labels": {"nodes": [{"name": "review-priority"}]},
                "timelineItems": {"nodes": [
                    {"label": {"name": "review-priority"}, "actor": {"login": "outsider"}},
                ]},
            }},
            "p2": {"pullRequest": None},
            "p3": {"pullRequest": {
                "state": "OPEN",
                "headRefOid": HEAD,
                "labels": {"nodes": [{"name": "triage"}]},
                "timelineItems": {"nodes": []},
            }},
        }
    }
    permission_reads: list[str] = []

    def fake_gh(*args: str, stdin: str | None = None) -> str:
        del stdin
        if args[:2] == ("api", "graphql"):
            return json.dumps(graphql)
        permission_reads.append(args[1])
        if args[1].endswith("/outsider/permission"):
            raise subprocess.CalledProcessError(1, args)
        return "write\n"

    monkeypatch.setattr(queue_priority, "_gh", fake_gh)
    states = queue_priority.fetch_live(
        {("o/a", 1), ("o/b", 2), ("o/c", 3), ("o/d", 4)},
        "review-priority",
    )

    assert states[("o/a", 1)] == PrState("OPEN", HEAD, priority=True)
    assert states[("o/b", 2)] == PrState("OPEN", NEW, priority=False)
    assert ("o/c", 3) not in states
    assert states[("o/d", 4)] == PrState("OPEN", HEAD, priority=False)
    assert permission_reads == [
        "repos/o/a/collaborators/maintainer/permission",
        "repos/o/b/collaborators/outsider/permission",
    ]


def test_main_records_then_cancels_only_still_queued_targets(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Apply mode records the exact plan before cancelling still-queued runs."""
    runs = [run(1, "o/a", 1), run(2, "o/b", 2), run(3, "o/c", 3)]
    live = {
        ("o/a", 1): PrState("OPEN", HEAD, priority=True),
        ("o/b", 2): PrState("OPEN", HEAD, priority=False),
        ("o/c", 3): PrState("CLOSED", HEAD, priority=False),
    }
    monkeypatch.setattr(queue_priority, "fetch_queued", lambda: runs)
    monkeypatch.setattr(queue_priority, "fetch_live", lambda keys, label: live)
    calls: list[tuple[tuple[str, ...], str | None]] = []

    def fake_gh(*args: str, stdin: str | None = None) -> str:
        calls.append((args, stdin))
        if args[-2:] == ("--jq", ".status"):
            return "queued\n" if "/3" in args[1] else "completed\n"
        return ""

    monkeypatch.setattr(queue_priority, "_gh", fake_gh)
    assert queue_priority.main([
        "--include-current", "--post-issue", "o/control#9", "--apply",
    ]) == 0

    output = capsys.readouterr().out
    assert "o/c\t3" in output and "stale" in output
    assert "o/b\t2" in output and "deferred" in output
    assert calls[0][0][:3] == ("issue", "comment", "9")
    assert calls[0][1] is not None and "Cancel list (TSV)" in calls[0][1]
    assert any(call[0][:3] == ("api", "-X", "POST") for call in calls)


def test_main_refuses_apply_without_an_audit_issue() -> None:
    """Cancellation cannot run without first naming its durable audit issue."""
    with pytest.raises(SystemExit, match="2"):
        queue_priority.main(["--apply"])


def test_subprocess_boundary_and_script_entrypoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """The CLI boundary preserves stdin and the module entrypoint exits cleanly."""
    recorded: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        recorded.update(command=command, kwargs=kwargs)
        stdout = "[]\n" if command == ["gh", "api", "example"] else ""
        return subprocess.CompletedProcess(command, 0, stdout=stdout)

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert queue_priority._gh("api", "example", stdin="payload") == "[]\n"
    assert recorded["command"] == ["gh", "api", "example"]
    assert recorded["kwargs"] == {
        "input": "payload", "capture_output": True, "text": True, "check": True,
    }

    monkeypatch.setattr(sys, "argv", [str(queue_priority.__file__)])
    with pytest.raises(SystemExit, match="0"):
        runpy.run_path(str(queue_priority.__file__), run_name="__main__")
>>>>>>> 38a1692b (merge: integrate latest review authority into CodeQL owner)
