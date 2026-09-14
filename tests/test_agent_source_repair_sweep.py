"""Bounded scheduler tests for explicit source-repair discovery."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from scripts.ci import agent_source_repair_sweep as sweep
from scripts.ci.agent_source_repair import (
    SourceRepairAlreadyClaimed,
    SourceRepairError,
    SourceRepairNotEnabled,
    SourceRepairNotRequested,
)


class FakeClient:
    """Minimal token-bearing client used only at the sweep orchestration boundary."""

    def __init__(self, response: Any = None) -> None:
        self.response = response
        self.calls: list[list[str]] = []

    def request(self, args: list[str], *, input_payload: Any = None) -> Any:
        self.calls.append(list(args))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _issue(number: int = 7) -> dict[str, Any]:
    return {"repository": "ContextualWisdomLab/bandscope", "number": number}


def _pull(state: str = "open") -> dict[str, Any]:
    return {"state": state}


def _comment(
    comment_id: int = 9001,
    *,
    association: str = "MEMBER",
    user_type: str = "User",
    body: str = "@cwl-source-fix\nFix it",
) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body,
        "author_association": association,
        "user": {"login": "maintainer", "type": user_type},
    }


def test_trusted_human_comment_prefilter() -> None:
    assert sweep._trusted_human_comment(_comment()) is True
    assert sweep._trusted_human_comment(_comment(association="NONE")) is False
    assert sweep._trusted_human_comment(_comment(user_type="Bot")) is False
    assert sweep._trusted_human_comment([]) is False
    assert sweep._trusted_human_comment({"user": "invalid", "author_association": "MEMBER"}) is False


def test_untrusted_malformed_command_cannot_consume_live_pr_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    monkeypatch.setattr(
        sweep,
        "list_recent_comments",
        lambda *args, **kwargs: [_comment(association="NONE", body="@cwl-source-fix")],
    )
    client = FakeClient(RuntimeError("untrusted comment consumed live PR validation"))
    called = False

    def unexpected(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("untrusted comment reached source-repair parsing")

    monkeypatch.setattr(sweep, "expected_from_comment", unexpected)
    assert sweep.sweep_source_repairs(
        target_client=client,
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (0, 0)
    assert client.calls == []
    assert called is False


@pytest.mark.parametrize("value", [0, 101])
def test_sweep_rejects_invalid_dispatch_limit(monkeypatch: pytest.MonkeyPatch, value: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        sweep.sweep_source_repairs(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="installation",
            lookback_hours=1,
            max_dispatches=value,
        )


def test_sweep_rejects_nonpositive_time_budget() -> None:
    with pytest.raises(ValueError, match="positive"):
        sweep.sweep_source_repairs(
            target_client=FakeClient(),
            dispatch_client=FakeClient(),
            organization="ContextualWisdomLab",
            repository_source="installation",
            lookback_hours=1,
            max_dispatches=1,
            time_budget_seconds=0,
        )


def test_sweep_dispatches_and_stops_at_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [_comment(), _comment(9002)])
    client = FakeClient(_pull())
    expected = object()
    monkeypatch.setattr(sweep, "expected_from_comment", lambda *args, **kwargs: expected)
    calls: list[bool] = []
    monkeypatch.setattr(
        sweep,
        "dispatch_source_repair",
        lambda **kwargs: calls.append(bool(kwargs["dry_run"])) or True,
    )
    assert sweep.sweep_source_repairs(
        target_client=client,
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=1,
        dry_run=True,
        now=datetime(2026, 9, 14, tzinfo=timezone.utc),
        time_budget_seconds=None,
    ) == (1, 0)
    assert calls == [True]


def test_sweep_counts_only_queued_repairs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [_comment(), _comment(9002)])
    client = FakeClient(_pull())
    monkeypatch.setattr(sweep, "expected_from_comment", lambda *args, **kwargs: object())
    outcomes = iter([False, True])
    monkeypatch.setattr(sweep, "dispatch_source_repair", lambda **kwargs: next(outcomes))
    assert sweep.sweep_source_repairs(
        target_client=client,
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (1, 0)


def test_sweep_skips_closed_or_malformed_live_pr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sweep,
        "list_recent_pull_requests",
        lambda *args, **kwargs: iter([_issue(7), _issue(8)]),
    )
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [_comment()])
    responses = iter([{"state": "closed"}, []])
    client = FakeClient()
    client.request = lambda *args, **kwargs: next(responses)  # type: ignore[method-assign]
    assert sweep.sweep_source_repairs(
        target_client=client,
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (0, 0)


def test_sweep_isolates_pr_fetch_failure(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("secret token")))
    assert sweep.sweep_source_repairs(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (0, 1)
    output = capsys.readouterr().out
    assert "warning" in output.lower()


@pytest.mark.parametrize(
    "exception",
    [SourceRepairNotRequested("no"), SourceRepairNotEnabled("off"), SourceRepairAlreadyClaimed("seen")],
)
def test_sweep_quietly_skips_expected_non_actionable_candidates(
    monkeypatch: pytest.MonkeyPatch, exception: Exception
) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [_comment()])
    client = FakeClient(_pull())
    monkeypatch.setattr(sweep, "expected_from_comment", lambda *args, **kwargs: (_ for _ in ()).throw(exception))
    assert sweep.sweep_source_repairs(
        target_client=client,
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (0, 0)


def test_sweep_isolates_source_and_unexpected_candidate_failures(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [_comment(), _comment(9002)])
    client = FakeClient(_pull())
    outcomes = iter([SourceRepairError("bad authority"), RuntimeError("provider secret")])

    def expected(*args: Any, **kwargs: Any) -> Any:
        raise next(outcomes)

    monkeypatch.setattr(sweep, "expected_from_comment", expected)
    assert sweep.sweep_source_repairs(
        target_client=client,
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (0, 2)
    assert capsys.readouterr().out.count("::warning::") == 2


def test_sweep_isolates_dispatch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    monkeypatch.setattr(sweep, "list_recent_comments", lambda *args, **kwargs: [_comment()])
    client = FakeClient(_pull())
    monkeypatch.setattr(sweep, "expected_from_comment", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        sweep,
        "dispatch_source_repair",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("dispatch failed")),
    )
    assert sweep.sweep_source_repairs(
        target_client=client,
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (0, 1)


def test_sweep_stops_before_new_issue_when_budget_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sweep, "list_recent_pull_requests", lambda *args, **kwargs: iter([_issue()]))
    ticks = iter([10.0, 11.0])
    monkeypatch.setattr(sweep.time, "monotonic", lambda: next(ticks))
    comments_called = False

    def comments(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        nonlocal comments_called
        comments_called = True
        return []

    monkeypatch.setattr(sweep, "list_recent_comments", comments)
    assert sweep.sweep_source_repairs(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=0.5,
    ) == (0, 0)
    assert comments_called is False


def test_sweep_isolates_repository_inventory_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("inventory failed")

    monkeypatch.setattr(sweep, "list_recent_pull_requests", explode)
    assert sweep.sweep_source_repairs(
        target_client=FakeClient(),
        dispatch_client=FakeClient(),
        organization="ContextualWisdomLab",
        repository_source="installation",
        lookback_hours=1,
        max_dispatches=20,
        time_budget_seconds=None,
    ) == (0, 1)


def test_main_requires_tokens_and_propagates_failure_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TARGET_REPOSITORY_TOKEN", raising=False)
    monkeypatch.delenv("AGENT_DISPATCH_TOKEN", raising=False)
    with pytest.raises(SystemExit):
        sweep.main([])

    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")
    tokens: list[str] = []
    monkeypatch.setattr(sweep, "GitHubClient", lambda token: tokens.append(token) or FakeClient())
    seen: dict[str, Any] = {}

    def fake_sweep(**kwargs: Any) -> tuple[int, int]:
        seen.update(kwargs)
        return 2, 1

    monkeypatch.setattr(sweep, "sweep_source_repairs", fake_sweep)
    assert sweep.main([
        "--repository-source", "organization",
        "--time-budget-seconds", "0",
        "--dry-run",
    ]) == 1
    assert tokens == ["target", "dispatch"]
    assert seen["repository_source"] == "organization"
    assert seen["time_budget_seconds"] is None
    assert seen["dry_run"] is True

    monkeypatch.setattr(sweep, "sweep_source_repairs", lambda **kwargs: (1, 0))
    assert sweep.main([]) == 0
