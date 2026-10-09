"""Operator runbook: prioritise the OpenCode dispatch queue without starving it."""

from __future__ import annotations

import json
import runpy
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from scripts.ci import opencode_queue_priority as queue

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

def test_metrics_report_zero_age_when_no_current_run_is_deferred() -> None:
    """An empty current-head queue must not invent a deferred age."""
    assert metrics(plan([], {}), now=NOW) == {
        "queued": 0,
        "deferred": 0,
        "stale": 0,
        "oldest_deferred_hours": 0.0,
        "priority_positions": {},
    }


def test_fetch_queued_parses_only_bound_dispatch_titles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unrelated queued workflows must not become cancellation candidates."""
    response = "\n".join(
        json.dumps(item)
        for item in [
            [101, "2026-09-29T06:30:00Z", "Review ContextualWisdomLab/naruon#974@abcdef0"],
            [102, "2026-09-29T06:31:00Z", "Review another-org/naruon#974@abcdef0"],
            [103, "2026-09-29T06:32:00Z", "Review ContextualWisdomLab/naruon#974@ABCDEF0"],
        ]
    )
    monkeypatch.setattr(queue, "_gh", lambda *_args, **_kwargs: response)

    assert queue.fetch_queued() == [
        QueuedRun(
            101,
            datetime(2026, 9, 29, 6, 30, tzinfo=timezone.utc),
            "ContextualWisdomLab/naruon",
            974,
            "abcdef0",
        )
    ]


def _pull_request_node(*, labels: list[str], events: list[dict]) -> dict:
    return {
        "state": "OPEN",
        "headRefOid": HEAD,
        "labels": {"nodes": [{"name": name} for name in labels]},
        "timelineItems": {"nodes": events},
    }


def test_fetch_live_accepts_only_a_writer_applied_priority_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A label without a trusted applying actor must not gain queue priority."""
    nodes = {
        "p0": {
            "pullRequest": _pull_request_node(labels=["other"], events=[]),
        },
        "p1": {
            "pullRequest": _pull_request_node(
                labels=["review-priority"],
                events=[
                    {"label": {"name": "other"}, "actor": {"login": "ignored"}},
                    {"label": {"name": "review-priority"}, "actor": None},
                    {"label": {"name": "review-priority"}, "actor": {"login": "alice"}},
                    {"label": {"name": "review-priority"}, "actor": {"login": "alice"}},
                ],
            ),
        },
        "p2": {
            "pullRequest": _pull_request_node(
                labels=["review-priority"],
                events=[
                    {"label": {"name": "review-priority"}, "actor": {"login": "bob"}},
                ],
            ),
        },
        "p3": None,
    }
    permission_requests: list[str] = []

    def fake_gh(*args: str, stdin: str | None = None) -> str:
        del stdin
        if args[:2] == ("api", "graphql"):
            return json.dumps({"data": nodes})
        endpoint = args[1]
        permission_requests.append(endpoint)
        if endpoint.endswith("/alice/permission"):
            return "write\n"
        raise subprocess.CalledProcessError(1, ["gh", *args])

    monkeypatch.setattr(queue, "_gh", fake_gh)
    live = queue.fetch_live(
        {
            ("ContextualWisdomLab/a", 1),
            ("ContextualWisdomLab/b", 2),
            ("ContextualWisdomLab/c", 3),
            ("ContextualWisdomLab/d", 4),
        },
        "review-priority",
    )

    assert live == {
        ("ContextualWisdomLab/a", 1): PrState("OPEN", HEAD, False),
        ("ContextualWisdomLab/b", 2): PrState("OPEN", HEAD, True),
        ("ContextualWisdomLab/c", 3): PrState("OPEN", HEAD, False),
    }
    assert permission_requests == [
        "repos/ContextualWisdomLab/b/collaborators/alice/permission",
        "repos/ContextualWisdomLab/c/collaborators/bob/permission",
    ]


def test_fetch_live_treats_null_graphql_data_as_no_live_pr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A null GraphQL payload must fail closed instead of fabricating PR state."""
    monkeypatch.setattr(queue, "_gh", lambda *_args, **_kwargs: '{"data": null}')
    assert queue.fetch_live({("ContextualWisdomLab/a", 1)}, "review-priority") == {}


def test_apply_requires_recording_the_cancel_list_first(capsys: pytest.CaptureFixture[str]) -> None:
    """The CLI must reject an apply request that has no audit issue."""
    with pytest.raises(SystemExit) as error:
        queue.main(["--apply"])

    assert error.value.code == 2
    assert "--apply requires --post-issue" in capsys.readouterr().err


def test_main_default_report_does_not_target_a_current_head_run(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Dry-run defaults must report, but not list, a non-priority current head."""
    current = run(2, "ContextualWisdomLab/a", 1)
    monkeypatch.setattr(queue, "fetch_queued", lambda: [current])
    monkeypatch.setattr(
        queue,
        "fetch_live",
        lambda _keys, _label: {(current.repo, current.pr): PrState("OPEN", HEAD, False)},
    )

    assert queue.main([]) == 0

    output = capsys.readouterr().out
    assert '"deferred": 1' in output
    assert output.endswith("run_id\tcreated_at\trepository\tpr\thead_sha\treason\n")


def test_main_records_targets_before_cancelling_only_still_queued_runs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Apply must record both reasons first and cancel only a queued target."""
    stale = run(1, "ContextualWisdomLab/a", 1, hour=3)
    current = run(2, "ContextualWisdomLab/b", 2, hour=4)
    priority = run(3, "ContextualWisdomLab/c", 3, hour=5)
    monkeypatch.setattr(queue, "fetch_queued", lambda: [stale, current, priority])
    monkeypatch.setattr(
        queue,
        "fetch_live",
        lambda _keys, _label: {
            (stale.repo, stale.pr): PrState("CLOSED", HEAD, False),
            (current.repo, current.pr): PrState("OPEN", HEAD, False),
            (priority.repo, priority.pr): PrState("OPEN", HEAD, True),
        },
    )
    calls: list[tuple[tuple[str, ...], str | None]] = []

    def fake_gh(*args: str, stdin: str | None = None) -> str:
        calls.append((args, stdin))
        if f"/runs/{stale.run_id}" in args[1] and args[-2:] == ("--jq", ".status"):
            return "queued\n"
        if f"/runs/{current.run_id}" in args[1] and args[-2:] == ("--jq", ".status"):
            return "completed\n"
        return ""

    monkeypatch.setattr(queue, "_gh", fake_gh)

    assert queue.main(
        [
            "--label",
            "urgent",
            "--include-current",
            "--post-issue",
            "ContextualWisdomLab/control#9",
            "--apply",
        ]
    ) == 0

    output = capsys.readouterr().out
    assert f"{stale.run_id}\t" in output and "\tstale\n" in output
    assert f"{current.run_id}\t" in output and "\tdeferred\n" in output
    assert "cancelled=1" in output
    assert calls[0][0] == (
        "issue",
        "comment",
        "9",
        "-R",
        "ContextualWisdomLab/control",
        "--body-file",
        "-",
    )
    assert "Label `urgent` (maintainer-applied) kept: 1. To cancel: 2." in (calls[0][1] or "")
    assert [args for args, _stdin in calls if args[-1].endswith("/cancel")] == [
        (
            "api",
            "-X",
            "POST",
            f"repos/{queue.CENTRAL}/actions/runs/{stale.run_id}/cancel",
        )
    ]


def test_script_entrypoint_reports_an_empty_queue(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Direct execution must invoke the CLI rather than silently doing nothing."""
    monkeypatch.setattr(sys, "argv", [queue.__file__])
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(stdout=""),
    )

    with pytest.raises(SystemExit) as error:
        runpy.run_path(queue.__file__, run_name="__main__")

    assert error.value.code == 0
    assert '"queued": 0' in capsys.readouterr().out
