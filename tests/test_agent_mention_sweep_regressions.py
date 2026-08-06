"""Review-driven pagination and failure-isolation regressions."""

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


def repository(name: str) -> dict:
    """Build one active organization repository record."""

    return {
        "full_name": f"ContextualWisdomLab/{name}",
        "owner": {"login": "ContextualWisdomLab"},
        "archived": False,
        "disabled": False,
    }


class PagingClient:
    """Serve page-aware endpoint responses and deterministic failures."""

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


def pull(number: int, updated_at: str = "2026-08-06T11:00:00Z") -> dict:
    """Build one pull-list response record."""

    return {"number": number, "updated_at": updated_at}


def test_pull_pagination_stops_at_cutoff_without_loading_later_pages() -> None:
    """Updated-descending pages stop immediately at the first old record."""

    sweep = module()
    recent = [pull(number) for number in range(1, 101)]
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
            ("repos/ContextualWisdomLab/example/pulls", 1): recent,
            ("repos/ContextualWisdomLab/example/pulls", 2): [
                pull(101, "2026-08-01T00:00:00Z")
            ],
        }
    )
    results = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
        )
    )
    assert len(results) == 100
    pull_calls = [
        args for args in client.calls if args[0].endswith("/pulls")
    ]
    assert len(pull_calls) == 2
    assert not any("page=3" in args for args in pull_calls)
    assert sweep.flatten_pages([{"number": 1}]) == [{"number": 1}]


def test_pull_pagination_stops_on_empty_followup_page() -> None:
    """A full page followed by an empty page terminates without page three."""

    sweep = module()
    recent = [pull(number) for number in range(1, 101)]
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
            ("repos/ContextualWisdomLab/example/pulls", 1): recent,
            ("repos/ContextualWisdomLab/example/pulls", 2): [],
        }
    )
    results = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
        )
    )
    assert len(results) == 100
    pull_calls = [
        args for args in client.calls if args[0].endswith("/pulls")
    ]
    assert len(pull_calls) == 2
    assert any("page=2" in args for args in pull_calls)
    assert not any("page=3" in args for args in pull_calls)


def test_invalid_pull_number_fails_closed_without_error_sink() -> None:
    """Malformed pull metadata raises when no isolation sink is supplied."""

    sweep = module()
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[repository("example")]],
            ("repos/ContextualWisdomLab/example/pulls", 1): [pull(0)],
        }
    )
    with pytest.raises(ValueError, match="invalid pull request number"):
        list(
            sweep.list_recent_pull_requests(
                client,
                organization="ContextualWisdomLab",
                repository_source="organization",
                since="2026-08-05T00:00:00Z",
            )
        )


def test_repository_failure_is_isolated_and_later_repository_runs() -> None:
    """A repository-local API failure does not terminate organization traversal."""

    sweep = module()
    client = PagingClient(
        {
            ("orgs/ContextualWisdomLab/repos", 1): [[
                repository("broken"),
                repository("healthy"),
            ]],
            ("repos/ContextualWisdomLab/broken/pulls", 1): RuntimeError(
                "forbidden"
            ),
            ("repos/ContextualWisdomLab/healthy/pulls", 1): [pull(7)],
        }
    )
    failures = []
    results = list(
        sweep.list_recent_pull_requests(
            client,
            organization="ContextualWisdomLab",
            repository_source="organization",
            since="2026-08-05T00:00:00Z",
            on_error=lambda scope, error: failures.append(
                (scope, str(error))
            ),
        )
    )
    assert [result["repository"] for result in results] == [
        "ContextualWisdomLab/healthy"
    ]
    assert failures == [("ContextualWisdomLab/broken", "forbidden")]


def mention_request(comment_id: int):
    """Build one Noema request for orchestration isolation tests."""

    router = importlib.import_module("agent_mention_router")
    return router.MentionRequest(
        "ContextualWisdomLab/example",
        7,
        "a" * 40,
        "main",
        comment_id,
        "maintainer",
        ("cwl-noema-review",),
    )


def test_sweep_continues_after_candidate_and_dispatch_failures(
    monkeypatch,
    capsys,
) -> None:
    """Candidate-local failures are counted while later work is queued."""

    sweep = module()
    issues = [
        {"repository": "ContextualWisdomLab/example", "number": 7},
        {"repository": "ContextualWisdomLab/example", "number": 8},
    ]
    monkeypatch.setattr(
        sweep,
        "list_recent_pull_requests",
        lambda *args, **kwargs: iter(issues),
    )

    def build_requests(client, *, issue, since):
        del client, since
        if issue["number"] == 7:
            raise RuntimeError("comment inventory failed")
        return (mention_request(10), mention_request(11))

    monkeypatch.setattr(sweep, "build_requests_for_pull_request", build_requests)
    dispatch_kwargs = []

    def dispatch(request, **kwargs):
        dispatch_kwargs.append(kwargs)
        if request.comment_id == 10:
            raise RuntimeError("dispatch failed")
        return ("@cwl-noema-review",)

    monkeypatch.setattr(sweep, "dispatch_request", dispatch)
    metrics = sweep.SweepMetrics()
    assert sweep.sweep(
        target_client=object(),
        dispatch_client=object(),
        organization="ContextualWisdomLab",
        repository_source="organization",
        lookback_hours=24,
        max_dispatches=5,
        opencode_allowlist=frozenset(),
        now=datetime(2026, 8, 6, tzinfo=timezone.utc),
        metrics=metrics,
    ) == 1
    assert metrics.failures == 2
    assert dispatch_kwargs[0]["ledger_artifact_cache"] is dispatch_kwargs[1][
        "ledger_artifact_cache"
    ]
    assert dispatch_kwargs[0]["dry_run"] is False
    output = capsys.readouterr().out
    assert "comment inventory failed" in output
    assert "dispatch failed" in output


def test_main_returns_failure_when_isolated_errors_were_observed(
    monkeypatch,
) -> None:
    """The scheduled workflow remains visibly failed after partial progress."""

    sweep = module()
    monkeypatch.setenv("TARGET_REPOSITORY_TOKEN", "target")
    monkeypatch.setenv("AGENT_DISPATCH_TOKEN", "dispatch")

    def fail_partially(**kwargs):
        kwargs["metrics"].failures = 1
        return 0

    monkeypatch.setattr(sweep, "sweep", fail_partially)
    assert sweep.main([]) == 1
