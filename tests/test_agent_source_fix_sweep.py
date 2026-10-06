from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "scripts" / "ci"))

import agent_source_fix_router as router  # noqa: E402
import agent_source_fix_sweep as sweep  # noqa: E402


HEAD = "a" * 40
BASE = "b" * 40


class FakeClient:
    def __init__(self, response: Any = None):
        self.response = response
        self.calls: list[list[str]] = []

    def request(self, args: list[str], input_payload: Any = None) -> Any:
        self.calls.append(list(args))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def issue() -> dict[str, Any]:
    return {
        "repository": "ContextualWisdomLab/.github",
        "number": 42,
        "pull_request": {"url": "https://api.github.com/pr/42"},
    }


def live_pull() -> dict[str, Any]:
    return {
        "state": "open",
        "head": {"sha": HEAD, "ref": "fix/current-pr"},
        "base": {"sha": BASE, "ref": "main"},
    }


def command_comment(comment_id: int = 7001) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": "@cwl-source-fix repair this PR",
        "author_association": "OWNER",
        "user": {"login": "seonghobae", "type": "User"},
    }


def receipt(comment_id: int = 7001) -> dict[str, Any]:
    return {
        "id": 9001,
        "body": f"<!-- cwl-source-fix-receipt:{comment_id} -->",
        "author_association": "NONE",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }


def request() -> router.SourceFixRequest:
    value = router.parse_event(
        {
            "repository": {"full_name": "ContextualWisdomLab/.github"},
            "issue": {"number": 42, "pull_request": {"url": "x"}},
            "comment": command_comment(),
            "pull_request": live_pull(),
        }
    )
    assert value is not None
    return value


def test_build_requests_reads_live_pr_and_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [command_comment()])
    client = FakeClient(live_pull())
    assert sweep.build_requests_for_pull_request(client, issue=issue(), since="2026-09-01T00:00:00Z") == (
        request(),
    )
    assert client.calls == [["repos/ContextualWisdomLab/.github/pulls/42"]]


def test_build_requests_stops_when_pr_is_not_open(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [command_comment()])
    assert sweep.build_requests_for_pull_request(
        FakeClient({"state": "closed"}), issue=issue(), since="2026-09-01T00:00:00Z"
    ) == ()
    assert sweep.build_requests_for_pull_request(
        FakeClient([]), issue=issue(), since="2026-09-01T00:00:00Z"
    ) == ()


def test_build_requests_does_not_rebind_old_command_after_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sweep,
        "list_recent_comments",
        lambda *args, **kwargs: [command_comment(), receipt()],
    )
    moved = live_pull()
    moved["head"]["sha"] = "c" * 40
    assert sweep.build_requests_for_pull_request(
        FakeClient(moved), issue=issue(), since="2026-09-01T00:00:00Z"
    ) == ()


@pytest.mark.parametrize("value", [0, 101])
def test_sweep_rejects_invalid_max_dispatches(value: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        sweep.sweep(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            lookback_hours=1,
            max_dispatches=value,
            repository_allowlist=frozenset(),
        )


def test_sweep_dispatches_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([issue()]))
    monkeypatch.setattr(sweep, "build_requests_for_pull_request", lambda *args, **kwargs: (request(),))
    calls: list[router.SourceFixRequest] = []
    monkeypatch.setattr(
        sweep,
        "dispatch_request",
        lambda value, **kwargs: calls.append(value) or True,
    )
    dispatched, failures = sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=20,
        repository_allowlist=frozenset({"ContextualWisdomLab/.github"}),
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
        time_budget_seconds=None,
    )
    assert (dispatched, failures) == (1, 0)
    assert len(calls) == 1


def test_sweep_counts_only_successful_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([issue()]))
    monkeypatch.setattr(
        sweep,
        "build_requests_for_pull_request",
        lambda *args, **kwargs: (request(), request()),
    )
    outcomes = iter([False, True])
    monkeypatch.setattr(sweep, "dispatch_request", lambda *args, **kwargs: next(outcomes))
    assert sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=20,
        repository_allowlist=frozenset(),
        time_budget_seconds=None,
    ) == (1, 0)


def test_sweep_stops_at_dispatch_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([issue()]))
    monkeypatch.setattr(
        sweep,
        "build_requests_for_pull_request",
        lambda *args, **kwargs: (request(), request()),
    )
    monkeypatch.setattr(sweep, "dispatch_request", lambda *args, **kwargs: True)
    assert sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=1,
        repository_allowlist=frozenset(),
        time_budget_seconds=None,
    ) == (1, 0)


def test_sweep_honors_time_budget_before_new_issue_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([issue()]))
    called = False

    def build(*args, **kwargs):
        nonlocal called
        called = True
        return ()

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", build)
    ticks = iter([10.0, 11.0])
    assert sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=20,
        repository_allowlist=frozenset(),
        time_budget_seconds=0.5,
        clock=lambda: next(ticks),
    ) == (0, 0)
    assert not called


def test_sweep_isolates_build_and_dispatch_failures(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    items = [issue(), {**issue(), "number": 43}]
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter(items))
    calls = 0

    def build(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("secret-ish build failure")
        return (request(),)

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", build)
    monkeypatch.setattr(sweep, "dispatch_request", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("dispatch failure")))
    assert sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=20,
        repository_allowlist=frozenset(),
        time_budget_seconds=None,
    ) == (0, 2)
    assert "warning" in capsys.readouterr().out


def test_sweep_isolates_repository_listing_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args, **kwargs):
        raise RuntimeError("listing failed")
        yield  # pragma: no cover

    monkeypatch.setattr(sweep, "list_recent_pull_requests", explode)
    assert sweep.sweep(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=1,
        max_dispatches=20,
        repository_allowlist=frozenset(),
        time_budget_seconds=None,
    ) == (0, 1)


def test_main_wires_tokens_and_cli(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["agent_source_fix_sweep.py", "--repository-source", "organization", "--dry-run"])
    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")
    monkeypatch.setenv("SOURCE_FIX_REPOSITORY_TARGETS", "ContextualWisdomLab/.github")
    tokens: list[str] = []
    monkeypatch.setattr(sweep, "GitHubClient", lambda token: tokens.append(token) or FakeClient())
    seen: dict[str, Any] = {}

    def fake_sweep(**kwargs):
        seen.update(kwargs)
        return 2, 1

    monkeypatch.setattr(sweep, "sweep", fake_sweep)
    assert sweep.main() == 0
    assert tokens == ["target", "dispatch"]
    assert seen["dry_run"] is True
    assert seen["repository_source"] == "organization"
    assert "2 dispatch(es), 1 isolated failure" in capsys.readouterr().out
