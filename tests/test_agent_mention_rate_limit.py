"""Fail-fast regressions for exhausted GitHub mention-router API budgets."""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts" / "ci"
sys.path.insert(0, str(SCRIPTS))


def module():
    """Reload the sweep module for isolated monkeypatching."""

    return importlib.reload(importlib.import_module("agent_mention_sweep"))


def test_primary_rate_limit_exhaustion_stops_the_sweep(monkeypatch) -> None:
    """A shared installation budget exhaustion must stop further API work."""

    sweep = module()
    issues = [
        {"repository": "ContextualWisdomLab/first", "number": 1},
        {"repository": "ContextualWisdomLab/second", "number": 2},
    ]
    monkeypatch.setattr(
        sweep,
        "list_recent_pull_requests",
        lambda *args, **kwargs: iter(issues),
    )
    visited: list[str] = []

    def build_requests(client, *, issue, since):
        del client, since
        visited.append(issue["repository"])
        raise RuntimeError(
            "gh: API rate limit exceeded for installation ID 141441800 (HTTP 403)"
        )

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", build_requests)
    metrics = sweep.SweepMetrics()

    with pytest.raises(sweep.SweepRateLimitExhausted, match="rate limit"):
        sweep.sweep(
            target_client=object(),
            dispatch_client=object(),
            organization="ContextualWisdomLab",
            repository_source="installation",
            lookback_hours=24,
            max_dispatches=5,
            opencode_allowlist=frozenset(),
            now=datetime(2026, 8, 15, tzinfo=timezone.utc),
            metrics=metrics,
        )

    assert visited == ["ContextualWisdomLab/first"]
    assert metrics.failures == 1


def test_secondary_rate_limit_exhaustion_is_global() -> None:
    """Secondary-limit messages are classified as sweep-global exhaustion."""

    sweep = module()
    assert sweep.is_rate_limit_exhaustion(
        RuntimeError("You have exceeded a secondary rate limit. Please retry later.")
    )
    assert sweep.is_rate_limit_exhaustion(
        RuntimeError("API rate limit already exceeded for installation ID 141441800")
    )
    assert sweep.is_rate_limit_exhaustion(
        RuntimeError("gh: You have exceeded a secondary rate limit (HTTP 429)")
    )
    assert not sweep.is_rate_limit_exhaustion(RuntimeError("Resource not accessible"))
    assert not sweep.is_rate_limit_exhaustion(RuntimeError("HTTP 403 Forbidden"))


class _PagingClient:
    """Serve page-aware endpoint responses and raise configured listing errors."""

    def __init__(self, responses) -> None:
        """Initialize an endpoint/page response map."""

        self.responses = responses
        self.calls: list[list[str]] = []

    def request(self, args, *, input_payload=None):
        """Return one endpoint/page response or raise its configured error."""

        del input_payload
        args = list(args)
        self.calls.append(args)
        endpoint = args[0]
        page = 1
        for index, value in enumerate(args[:-1]):
            if value == "-f" and args[index + 1].startswith("page="):
                page = int(args[index + 1].split("=", 1)[1])
        response = self.responses[(endpoint, page)]
        if isinstance(response, Exception):
            raise response
        return response


def _repository(name: str) -> dict:
    """Build one active organization repository record."""

    return {
        "full_name": f"ContextualWisdomLab/{name}",
        "owner": {"login": "ContextualWisdomLab"},
        "archived": False,
        "disabled": False,
    }


def test_repository_listing_rate_limit_stops_before_later_repository(
    monkeypatch,
    capsys,
) -> None:
    """The 116-failure incident path: first repo listing exhausts the shared budget."""

    sweep = module()
    client = _PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[
                _repository("first"),
                _repository("second"),
            ]],
            ("repos/ContextualWisdomLab/first/pulls", 1): RuntimeError(
                "gh: API rate limit exceeded for installation ID 141441800 (HTTP 403)"
            ),
            ("repos/ContextualWisdomLab/second/pulls", 1): [
                {"number": 2, "updated_at": "2026-08-15T11:00:00Z"}
            ],
        }
    )

    def refuse_later_work(*args, **kwargs):
        del args, kwargs
        raise AssertionError("later pull requests must not be built after listing exhaustion")

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", refuse_later_work)
    metrics = sweep.SweepMetrics()

    with pytest.raises(sweep.SweepRateLimitExhausted, match="rate limit"):
        sweep.sweep(
            target_client=client,
            dispatch_client=object(),
            organization="ContextualWisdomLab",
            repository_source="organization",
            lookback_hours=24,
            max_dispatches=5,
            opencode_allowlist=frozenset(),
            now=datetime(2026, 8, 15, tzinfo=timezone.utc),
            metrics=metrics,
        )

    pull_calls = [args[0] for args in client.calls if args[0].endswith("/pulls")]
    assert pull_calls == ["repos/ContextualWisdomLab/first/pulls"]
    assert metrics.failures == 1
    output = capsys.readouterr().out
    assert "::error::" in output
    assert "ContextualWisdomLab/first" in output
    assert "do not re-run" in output.casefold() or "wait" in output.casefold()


def test_dispatch_rate_limit_stops_before_later_pull_request(monkeypatch) -> None:
    """A shared-budget failure while dispatching must not touch the next PR."""

    sweep = module()
    issues = [
        {"repository": "ContextualWisdomLab/first", "number": 1},
        {"repository": "ContextualWisdomLab/second", "number": 2},
    ]
    monkeypatch.setattr(
        sweep,
        "list_recent_pull_requests",
        lambda *args, **kwargs: iter(issues),
    )
    visited: list[int] = []

    def build_requests(client, *, issue, since):
        del client, since
        visited.append(issue["number"])
        router = importlib.import_module("agent_mention_router")
        return (
            router.MentionRequest(
                issue["repository"],
                issue["number"],
                "a" * 40,
                "main",
                issue["number"] * 10,
                "maintainer",
                ("opencode-agent",),
            ),
        )

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", build_requests)

    def dispatch(request, **kwargs):
        del kwargs
        raise RuntimeError(
            "gh: API rate limit exceeded for installation ID 141441800 (HTTP 403)"
        )

    monkeypatch.setattr(sweep, "dispatch_request", dispatch)
    metrics = sweep.SweepMetrics()

    with pytest.raises(sweep.SweepRateLimitExhausted, match="rate limit"):
        sweep.sweep(
            target_client=object(),
            dispatch_client=object(),
            organization="ContextualWisdomLab",
            repository_source="installation",
            lookback_hours=24,
            max_dispatches=5,
            opencode_allowlist=frozenset(),
            now=datetime(2026, 8, 15, tzinfo=timezone.utc),
            metrics=metrics,
        )

    assert visited == [1]
    assert metrics.failures == 1


def test_main_returns_failure_when_shared_rate_limit_stops_sweep(
    monkeypatch,
    capsys,
) -> None:
    """The scheduled job must exit 1 with an operator next action, not a traceback."""

    sweep = module()
    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")

    def raise_exhausted(**kwargs):
        kwargs["metrics"].failures = 1
        raise sweep.SweepRateLimitExhausted(
            "GitHub API rate limit exhausted; stopping organization sweep "
            "to preserve the shared installation budget"
        )

    monkeypatch.setattr(sweep, "sweep", raise_exhausted)
    assert sweep.main([]) == 1
    output = capsys.readouterr().out
    assert "::error::" in output
    assert "rate limit" in output.casefold()
    assert "wait" in output.casefold() or "do not re-run" in output.casefold()
