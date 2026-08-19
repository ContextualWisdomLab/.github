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
    assert not sweep.is_rate_limit_exhaustion(RuntimeError("Resource not accessible"))


def test_main_reports_rate_limit_reset_and_returns_failure(monkeypatch, capsys) -> None:
    """The scheduled CLI reports the shared-budget stop without a traceback."""

    sweep = module()
    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")
    def fail_for_rate_limit(**kwargs):
        del kwargs
        raise sweep.SweepRateLimitExhausted(
            "wait for the budget reset before retrying"
        )

    monkeypatch.setattr(sweep, "sweep", fail_for_rate_limit)

    assert sweep.main([]) == 1
    assert "wait for the budget reset before retrying" in capsys.readouterr().out
